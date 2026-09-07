"""Retry scheduling, lease recovery and durable event delivery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.domain.jobs import JobState, claim_job, is_lease_expired
from app.domain.models import OutboxEvent, ProcessingJob
from app.infra import outbox as outbox_module
from app.infra.jobs import claim_job_for_execution, due_jobs, enqueue_job, fail_job_for_execution
from app.infra.outbox import (
    DESTINATION_ANALYTICS,
    dispatch_analytics_events,
    enqueue_analytics_event,
)
from tests.conftest import requires_db

pytestmark = requires_db


async def test_a_failed_retryable_job_gets_a_future_due_time(db) -> None:
    """The backoff was computed and discarded before; it must be persisted."""
    job, _ = await enqueue_job(db, "fetch_source_page", "retry-1", {})
    await claim_job_for_execution(db, job.job_id)
    await fail_job_for_execution(db, job, "connection reset")

    await db.refresh(job)
    assert job.state == JobState.retry_wait.value
    assert job.next_attempt_at is not None
    assert job.next_attempt_at > datetime.now(UTC)
    assert job.lease_expires_at is None, "a failed job holds no lease"


async def test_a_job_cannot_be_claimed_before_its_backoff_elapses(db) -> None:
    job, _ = await enqueue_job(db, "fetch_source_page", "retry-2", {})
    await claim_job_for_execution(db, job.job_id)
    await fail_job_for_execution(db, job, "temporary")

    with pytest.raises(ValueError, match="not due yet"):
        await claim_job_for_execution(db, job.job_id)


async def test_due_jobs_excludes_work_still_waiting(db) -> None:
    ready, _ = await enqueue_job(db, "normalize_discovery", "ready", {})
    waiting, _ = await enqueue_job(db, "fetch_source_page", "waiting", {})
    await claim_job_for_execution(db, waiting.job_id)
    await fail_job_for_execution(db, waiting, "temporary")

    due = await due_jobs(db)
    assert [job.job_id for job in due] == [ready.job_id]


async def test_claiming_takes_a_lease(db) -> None:
    job, _ = await enqueue_job(db, "normalize_discovery", "lease-1", {})
    await claim_job_for_execution(db, job.job_id)
    await db.refresh(job)
    assert job.lease_expires_at is not None
    assert job.lease_expires_at > datetime.now(UTC)


async def test_an_abandoned_claim_is_returned_to_the_queue(db) -> None:
    """A worker that dies mid-flight must not strand its job in running."""
    from app.infra.jobs import reconcile_stuck_jobs

    job, _ = await enqueue_job(db, "fetch_source_page", "stuck-1", {})
    await claim_job_for_execution(db, job.job_id)
    # Simulate the worker dying: the lease elapses with nobody to renew it.
    job.lease_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db.commit()

    assert await reconcile_stuck_jobs(db) == 1
    await db.refresh(job)
    assert job.state == JobState.retry_wait.value
    assert job.last_error == "lease expired before completion"
    assert job.next_attempt_at is not None


async def test_a_live_lease_is_left_alone(db) -> None:
    from app.infra.jobs import reconcile_stuck_jobs

    job, _ = await enqueue_job(db, "fetch_source_page", "stuck-2", {})
    await claim_job_for_execution(db, job.job_id)
    assert await reconcile_stuck_jobs(db) == 0
    await db.refresh(job)
    assert job.state == JobState.running.value


def test_lease_expiry_is_a_pure_check() -> None:
    now = datetime.now(UTC)
    assert is_lease_expired(now - timedelta(seconds=1), now=now) is True
    assert is_lease_expired(now + timedelta(seconds=1), now=now) is False
    assert is_lease_expired(None, now=now) is False


def test_a_job_past_its_due_time_is_claimable() -> None:
    now = datetime.now(UTC)
    transition = claim_job(
        JobState.retry_wait, 1, now=now, next_attempt_at=now - timedelta(seconds=1)
    )
    assert transition.state == JobState.running


async def test_an_analytics_event_is_written_once_per_dedupe_key(db) -> None:
    for _ in range(3):
        await enqueue_analytics_event(
            db, event_type="thing_happened", dedupe_key="same", payload={"n": 1}
        )
    await db.commit()
    events = list(await db.scalars(select(OutboxEvent)))
    assert len(events) == 1
    assert events[0].destination == DESTINATION_ANALYTICS


async def test_pending_events_are_held_rather_than_marked_delivered(db) -> None:
    """No PostHog key/gate is configured in tests by default, so nothing may
    claim delivery - this must stay true regardless of what's deployed."""
    await enqueue_analytics_event(db, event_type="thing", dedupe_key="held-1", payload={})
    await db.commit()

    result = await dispatch_analytics_events(db)
    assert result == {"held": 1, "dispatched": 0}

    event = await db.scalar(select(OutboxEvent))
    assert event.state == "pending", "an undelivered event must not be marked dispatched"
    assert event.dispatched_at is None


@dataclass(frozen=True)
class _FakeSettings:
    posthog_dispatch_active: bool
    posthog_api_key: str | None
    posthog_host: str = "https://posthog.test"


async def test_dispatch_is_held_when_the_gate_is_off_even_with_a_key(db, monkeypatch) -> None:
    """The environment gate and the key are both required - a key alone
    (e.g. left set while ENVIRONMENT is switched back to development) must
    not be enough to start sending real events."""
    monkeypatch.setattr(
        outbox_module, "get_settings", lambda: _FakeSettings(False, "a-real-key")
    )
    await enqueue_analytics_event(db, event_type="thing", dedupe_key="gated-1", payload={})
    await db.commit()

    result = await dispatch_analytics_events(db)
    assert result == {"held": 1, "dispatched": 0}


async def test_dispatch_sends_and_marks_dispatched_on_success(db, monkeypatch) -> None:
    monkeypatch.setattr(
        outbox_module, "get_settings", lambda: _FakeSettings(True, "a-real-key")
    )
    sent_batches = []

    async def _fake_send_batch(events, *, api_key, host, timeout=10.0):
        sent_batches.append((api_key, host, events))

    monkeypatch.setattr(outbox_module, "send_batch", _fake_send_batch)
    await enqueue_analytics_event(
        db, event_type="scholarship_search_completed", dedupe_key="sent-1", payload={"n": 1}
    )
    await db.commit()

    result = await dispatch_analytics_events(db)
    assert result == {"held": 0, "dispatched": 1}
    assert sent_batches[0][0] == "a-real-key"
    assert sent_batches[0][1] == "https://posthog.test"

    event = await db.scalar(select(OutboxEvent))
    assert event.state == "dispatched"
    assert event.dispatched_at is not None


async def test_dispatch_marks_failed_and_eventually_dead_letters(db, monkeypatch) -> None:
    monkeypatch.setattr(
        outbox_module, "get_settings", lambda: _FakeSettings(True, "a-real-key")
    )

    async def _failing_send_batch(events, *, api_key, host, timeout=10.0):
        raise httpx.HTTPStatusError(
            "boom", request=httpx.Request("POST", host), response=httpx.Response(500)
        )

    monkeypatch.setattr(outbox_module, "send_batch", _failing_send_batch)
    await enqueue_analytics_event(db, event_type="thing", dedupe_key="fail-1", payload={})
    await db.commit()

    for _ in range(outbox_module.MAX_DISPATCH_ATTEMPTS - 1):
        result = await dispatch_analytics_events(db)
        assert result == {"held": 0, "dispatched": 0, "failed": 1}
        event = await db.scalar(select(OutboxEvent))
        assert event.state == "pending"

    await dispatch_analytics_events(db)
    event = await db.scalar(select(OutboxEvent))
    assert event.state == "dead_letter"
    assert event.attempts == outbox_module.MAX_DISPATCH_ATTEMPTS
    assert "boom" in event.payload["last_error"]


async def test_the_worker_runs_the_maintenance_kinds(db) -> None:
    from app.infra.worker import execute_job

    for kind in ("dispatch_outbox", "reconcile_stuck_jobs", "refresh_status", "reverify_due"):
        job, _ = await enqueue_job(db, kind, f"maintenance-{kind}", {})
        assert await execute_job(db, job.job_id) == "completed"
        stored = await db.scalar(select(ProcessingJob).where(ProcessingJob.job_id == job.job_id))
        assert stored.state == "completed"
