from datetime import UTC, datetime

import pytest

from app.domain.jobs import JobState, claim_job, fail_job


def test_claim_increments_attempts() -> None:
    transition = claim_job(JobState.queued, 0)
    assert transition.state == JobState.running
    assert transition.attempts == 1


def test_retryable_job_uses_bounded_retries() -> None:
    transition = fail_job("fetch_source_page", 1, "temporary error", now=datetime.now(UTC))
    assert transition.state == JobState.retry_wait
    assert transition.next_attempt_at is not None


def test_exhausted_or_non_retryable_job_goes_to_review() -> None:
    assert fail_job("normalize_discovery", 1, "bad data").state == JobState.failed_review
    assert fail_job("fetch_source_page", 5, "repeated error").state == JobState.failed_review


def test_running_job_cannot_be_claimed_twice() -> None:
    with pytest.raises(ValueError):
        claim_job(JobState.running, 1)
