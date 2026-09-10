"""A QStash *schedule* redelivers one static body forever; ProcessingJob's
dedupe_key is permanently unique, so a recurring job kind must compute its
own key server-side rather than trust whatever the static body carries -
otherwise only the first-ever delivery would run."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.api.job_schemas import JobRequest
from app.api.routes import (
    RECURRING_QUARTER_HOUR_KINDS,
    RECURRING_WEEKLY_KINDS,
    _enqueue,
    _quarter_hour_dedupe_key,
    _weekly_dedupe_key,
)
from app.domain.models import ProcessingJob
from tests.conftest import requires_db


def test_harvest_parsebot_is_a_recurring_weekly_kind() -> None:
    assert "harvest_parsebot" in RECURRING_WEEKLY_KINDS


def test_sync_countries_is_a_recurring_weekly_kind() -> None:
    assert "sync_countries" in RECURRING_WEEKLY_KINDS


def test_weekly_dedupe_key_is_stable_within_the_same_call() -> None:
    first = _weekly_dedupe_key("harvest_parsebot")
    second = _weekly_dedupe_key("harvest_parsebot")
    assert first == second
    assert first.startswith("harvest_parsebot:")


def test_weekly_dedupe_key_differs_by_kind() -> None:
    assert _weekly_dedupe_key("harvest_parsebot") != _weekly_dedupe_key("other_kind")


def test_freshness_kinds_are_recurring_quarter_hour_kinds() -> None:
    assert "refresh_status" in RECURRING_QUARTER_HOUR_KINDS
    assert "reverify_due" in RECURRING_QUARTER_HOUR_KINDS
    assert "sweep_due_jobs" in RECURRING_QUARTER_HOUR_KINDS


def test_quarter_hour_dedupe_key_is_stable_within_the_same_bucket() -> None:
    first = _quarter_hour_dedupe_key("refresh_status")
    second = _quarter_hour_dedupe_key("refresh_status")
    assert first == second
    assert first.startswith("refresh_status:")


def test_quarter_hour_dedupe_key_differs_by_kind() -> None:
    assert _quarter_hour_dedupe_key("refresh_status") != _quarter_hour_dedupe_key("reverify_due")


def test_quarter_hour_dedupe_key_differs_across_a_bucket_boundary(monkeypatch) -> None:
    import app.api.routes as routes_module

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 6, 15, 12, 14, 59, tzinfo=UTC)

    monkeypatch.setattr(routes_module, "datetime", _FrozenDatetime)
    before = _quarter_hour_dedupe_key("refresh_status")

    class _NextBucket(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 6, 15, 12, 15, 0, tzinfo=UTC)

    monkeypatch.setattr(routes_module, "datetime", _NextBucket)
    after = _quarter_hour_dedupe_key("refresh_status")

    assert before != after
    assert before == "refresh_status:2026-06-15T12:00:00+00:00"
    assert after == "refresh_status:2026-06-15T12:15:00+00:00"


@requires_db
async def test_the_schedules_own_placeholder_key_gets_recomputed(db) -> None:
    """Every manage_*_schedule.py script sends this exact static dedupe_key -
    that delivery, and only that one, should get the recurring bucket key."""
    response = await _enqueue(
        "refresh_status", JobRequest(dedupe_key="refresh_status:scheduled", payload={}), db
    )
    job = await db.scalar(select(ProcessingJob).where(ProcessingJob.job_id == response.job_id))
    assert job.dedupe_key == _quarter_hour_dedupe_key("refresh_status")


@requires_db
async def test_a_manual_dedupe_key_on_a_recurring_kind_is_honored_as_is(db) -> None:
    """An operator forcing an out-of-band re-run with their own dedupe_key
    (e.g. sync_job.json's manually-incremented key) must not be silently
    collapsed into the same bucket the schedule already ran this period."""
    response = await _enqueue(
        "refresh_status", JobRequest(dedupe_key="manual-refresh-1", payload={}), db
    )
    job = await db.scalar(select(ProcessingJob).where(ProcessingJob.job_id == response.job_id))
    assert job.dedupe_key == "manual-refresh-1"
