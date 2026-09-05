import uuid

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.linking import LinkOutcome, decide_link
from app.domain.models import Discovery, ReviewTask, Scholarship
from app.infra.jobs import enqueue_job


async def link_discovery(db: AsyncSession, discovery_id: uuid.UUID) -> LinkOutcome:
    discovery = await db.scalar(
        select(Discovery).where(Discovery.discovery_id == discovery_id).with_for_update()
    )
    if discovery is None:
        raise LookupError("Discovery not found")
    candidates = await db.scalars(
        select(Scholarship.scholarship_id).where(Scholarship.name.ilike(discovery.raw_title or ""))
    )
    decision = decide_link([str(value) for value in candidates])
    if decision.outcome == LinkOutcome.linked:
        discovery.canonical_scholarship_id = uuid.UUID(decision.scholarship_id)
        discovery.processing_state = LinkOutcome.linked.value
    elif decision.outcome == LinkOutcome.needs_review:
        discovery.processing_state = LinkOutcome.needs_review.value
        await _add_review_task_once(db, discovery.discovery_id, decision.reason, priority=50)
    else:
        # A brand-new identity is still a decision a reviewer must make before
        # it can ever be published. Against an empty or young catalogue this is
        # the outcome nearly every discovery gets, so without a task here it
        # would sit invisible - new_candidate has no other path into the queue.
        discovery.processing_state = LinkOutcome.new_candidate.value
        await _add_review_task_once(db, discovery.discovery_id, decision.reason)
    await db.commit()
    return decision.outcome


async def _add_review_task_once(
    db: AsyncSession, discovery_id: uuid.UUID, reason: str, *, priority: int = 100
) -> None:
    """Keep repeated deliveries from multiplying one discovery's queue task.

    QStash and the admin runner are both at-least-once execution paths. The
    processing-job dedupe key prevents duplicate jobs, but an already-created
    job can still be replayed while older data is being repaired - including
    two overlapping runs of the job itself, not just a resend of the same
    message. A check-then-insert here still leaves a real race between the
    SELECT and the INSERT, so the uniqueness has to be enforced by the
    database (uq_review_tasks_open_per_discovery), the same way enqueue_job
    lets the dedupe_key's own unique index arbitrate concurrent inserts
    instead of trusting an application-level check.

    A task actually created here is the only path a review task has into
    existence, so it is also the one place to enqueue prepare_review for it -
    a discovery relinked into its existing task must not re-draft it.
    """
    inserted = await db.execute(
        insert(ReviewTask)
        .values(discovery_id=discovery_id, reason=reason, priority=priority)
        .on_conflict_do_nothing(
            index_elements=["discovery_id"],
            index_where=text("state = 'open' AND resolution IS NULL"),
        )
        .returning(ReviewTask.review_task_id)
    )
    review_task_id = inserted.scalar_one_or_none()
    if review_task_id is not None:
        await enqueue_job(
            db,
            "prepare_review",
            f"prepare_review:{review_task_id}",
            {"review_task_id": str(review_task_id)},
        )
