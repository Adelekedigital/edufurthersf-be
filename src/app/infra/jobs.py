import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_uuid7
from app.domain.jobs import JobState, claim_job, fail_job, finish_job, lease_expiry
from app.domain.models import ProcessingJob


async def enqueue_job(
    db: AsyncSession, kind: str, dedupe_key: str, payload: dict
) -> tuple[ProcessingJob, bool]:
    """Insert a job once, tolerating concurrent duplicate deliveries.

    QStash delivers at least once, so the same message can arrive twice at the
    same moment. A check-then-insert lets both callers past the SELECT and the
    loser's commit raises IntegrityError on the unique dedupe key, which
    surfaced as a 500. Let the database arbitrate instead.
    """
    inserted = await db.execute(
        insert(ProcessingJob)
        .values(job_id=new_uuid7(), kind=kind, dedupe_key=dedupe_key, payload=payload)
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
        .returning(ProcessingJob.job_id)
    )
    job_id = inserted.scalar_one_or_none()
    await db.commit()
    job = await db.scalar(select(ProcessingJob).where(ProcessingJob.dedupe_key == dedupe_key))
    if job is None:  # pragma: no cover - the row was just committed
        raise LookupError("Job disappeared immediately after insert")
    return job, job_id is not None


async def claim_job_for_execution(db: AsyncSession, job_id: uuid.UUID) -> ProcessingJob:
    job = await db.scalar(
        select(ProcessingJob).where(ProcessingJob.job_id == job_id).with_for_update()
    )
    if job is None:
        raise LookupError("Job not found")
    transition = claim_job(job.state, job.attempts, next_attempt_at=job.next_attempt_at)
    job.state = transition.state.value
    job.attempts = transition.attempts
    # Hold a lease so a worker that dies mid-flight does not strand the row in
    # running forever; reconcile_stuck_jobs returns expired leases to the queue.
    job.lease_expires_at = lease_expiry()
    await db.commit()
    return job


async def complete_job(db: AsyncSession, job: ProcessingJob) -> None:
    transition = finish_job()
    job.state = transition.state.value
    job.lease_expires_at = None
    job.next_attempt_at = None
    await db.commit()


async def fail_job_for_execution(db: AsyncSession, job: ProcessingJob, error: str) -> None:
    transition = fail_job(job.kind, job.attempts, error)
    job.state = transition.state.value
    job.last_error = transition.error
    # Persist the computed backoff. Without this a retry was eligible instantly
    # and the exponential schedule had no effect at all.
    job.next_attempt_at = transition.next_attempt_at
    job.lease_expires_at = None
    await db.commit()


async def reconcile_stuck_jobs(db: AsyncSession, *, limit: int = 100) -> int:
    """Return abandoned claims to the queue.

    A worker that crashes after claiming leaves a row in running with a lease
    nobody will renew. Without this sweep that work is never retried and never
    visible as failed.
    """
    now = datetime.now(UTC)
    stuck = list(
        await db.scalars(
            select(ProcessingJob)
            .where(
                ProcessingJob.state == JobState.running.value,
                ProcessingJob.lease_expires_at.is_not(None),
                ProcessingJob.lease_expires_at <= now,
            )
            .order_by(ProcessingJob.job_id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    for job in stuck:
        transition = fail_job(job.kind, job.attempts, "lease expired before completion", now=now)
        job.state = transition.state.value
        job.last_error = transition.error
        job.next_attempt_at = transition.next_attempt_at
        job.lease_expires_at = None
    await db.commit()
    return len(stuck)


async def due_jobs(db: AsyncSession, *, limit: int = 100) -> list[ProcessingJob]:
    """Jobs that are queued, or waiting and now past their backoff."""
    now = datetime.now(UTC)
    rows = await db.scalars(
        select(ProcessingJob)
        .where(
            ProcessingJob.state.in_([JobState.queued.value, JobState.retry_wait.value]),
            or_(ProcessingJob.next_attempt_at.is_(None), ProcessingJob.next_attempt_at <= now),
        )
        .order_by(ProcessingJob.job_id)
        .limit(limit)
    )
    return list(rows)
