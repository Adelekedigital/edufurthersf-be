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


#: How long a claim is held before a sweeper may reclaim it. Long enough for a
#: bounded handler to finish, short enough that a crashed worker frees its work.
LEASE_SECONDS = 900


def claim_job(
    state: str,
    attempts: int,
    *,
    now: datetime | None = None,
    next_attempt_at: datetime | None = None,
) -> JobTransition:
    """Move a queued or waiting job into running, honouring its backoff."""
    current = now or datetime.now(UTC)
    if state not in {JobState.queued, JobState.retry_wait}:
        raise ValueError("Job is not claimable")
    if next_attempt_at is not None and next_attempt_at > current:
        raise ValueError("Job is not due yet")
    return JobTransition(JobState.running, attempts + 1, None, None)


def lease_expiry(now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) + timedelta(seconds=LEASE_SECONDS)


def is_lease_expired(lease_expires_at: datetime | None, *, now: datetime | None = None) -> bool:
    """A running job whose lease has elapsed is presumed abandoned."""
    if lease_expires_at is None:
        return False
    return lease_expires_at <= (now or datetime.now(UTC))


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
