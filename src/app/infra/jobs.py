import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_uuid7
from app.domain.jobs import claim_job, fail_job, finish_job
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
    transition = claim_job(job.state, job.attempts)
    job.state = transition.state.value
    job.attempts = transition.attempts
    await db.commit()
    return job


async def complete_job(db: AsyncSession, job: ProcessingJob) -> None:
    transition = finish_job()
    job.state = transition.state.value
    await db.commit()


async def fail_job_for_execution(db: AsyncSession, job: ProcessingJob, error: str) -> None:
    transition = fail_job(job.kind, job.attempts, error)
    job.state = transition.state.value
    job.last_error = transition.error
    await db.commit()
