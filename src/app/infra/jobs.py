import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs import claim_job, fail_job, finish_job
from app.domain.models import ProcessingJob


async def enqueue_job(
    db: AsyncSession, kind: str, dedupe_key: str, payload: dict
) -> tuple[ProcessingJob, bool]:
    existing = await db.scalar(select(ProcessingJob).where(ProcessingJob.dedupe_key == dedupe_key))
    if existing:
        return existing, False
    job = ProcessingJob(job_id=uuid.uuid4(), kind=kind, dedupe_key=dedupe_key, payload=payload)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job, True


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
