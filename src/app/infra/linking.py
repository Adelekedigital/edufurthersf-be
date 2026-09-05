import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.linking import LinkOutcome, decide_link
from app.domain.models import Discovery, ReviewTask, Scholarship


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
    job can still be replayed while older data is being repaired. Review-task
    creation therefore needs its own idempotency guard as well.
    """
    existing = await db.scalar(
        select(ReviewTask.review_task_id)
        .where(
            ReviewTask.discovery_id == discovery_id,
            ReviewTask.state == "open",
            ReviewTask.resolution.is_(None),
        )
        .limit(1)
    )
    if existing is None:
        db.add(ReviewTask(discovery_id=discovery_id, reason=reason, priority=priority))
