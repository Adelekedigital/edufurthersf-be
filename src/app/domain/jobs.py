from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum


class JobState(StrEnum):
    queued = "queued"
    running = "running"
    retry_wait = "retry_wait"
    completed = "completed"
    failed_review = "failed_review"


RETRYABLE_KINDS = {"fetch_source_page", "extract_candidate", "dispatch_outbox"}


@dataclass(frozen=True)
class JobTransition:
    state: JobState
    attempts: int
    next_attempt_at: datetime | None
    error: str | None


def claim_job(state: str, attempts: int, *, now: datetime | None = None) -> JobTransition:
    if state not in {JobState.queued, JobState.retry_wait}:
        raise ValueError("Job is not claimable")
    return JobTransition(JobState.running, attempts + 1, None, None)


def finish_job() -> JobTransition:
    return JobTransition(JobState.completed, 0, None, None)


def fail_job(kind: str, attempts: int, error: str, *, now: datetime | None = None) -> JobTransition:
    current = now or datetime.now(UTC)
    safe_error = error[:1000]
    if kind in RETRYABLE_KINDS and attempts < 5:
        delay = min(60 * (2 ** max(attempts - 1, 0)), 21600)
        return JobTransition(
            JobState.retry_wait, attempts, current + timedelta(seconds=delay), safe_error
        )
    return JobTransition(JobState.failed_review, attempts, None, safe_error)
