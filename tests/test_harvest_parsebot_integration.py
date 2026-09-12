"""The app-level kill switch: harvest_parsebot must not touch the network at
all when neither Source is registered/active, not just discard the result.

Also covers the harvest-health tracking (_update_harvest_health): a
Parse.bot-backed Source's underlying scraper-as-API can break silently (the
target site changed, the marketplace listing broke) - a consecutive-failure
counter on the Source row makes that visible, reset on any success.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.domain.models import Source
from app.domain.parsebot_harvest import SCHOLARSHIPPORTAL_SOURCE_NAME
from app.infra import worker as worker_module
from app.infra.worker import _harvest_parsebot, _update_harvest_health
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.mark.anyio
async def test_harvest_is_a_no_op_with_no_active_source(db) -> None:
    # No ScholarshipPortal/PhDScanner Source registered in this clean test
    # database - _harvest_parsebot must return cleanly without ever
    # constructing a Parse SDK client (which would require PARSE_API_KEY and
    # a real network call neither is available in this suite).
    await _harvest_parsebot(db)


async def _scholarshipportal_source(db) -> Source:
    source = Source(
        name=SCHOLARSHIPPORTAL_SOURCE_NAME,
        source_type="parsebot_api",
        authority_grade="C",
        approved_domains=["scholarshipportal.com"],
        active=True,
    )
    db.add(source)
    await db.commit()
    return source


def _always_raises(destination, study_level, *, limit=20):
    raise RuntimeError("upstream is down")


def _always_empty(destination, study_level, *, limit=20):
    return []


async def test_every_call_failing_increments_the_counter(db, monkeypatch) -> None:
    source = await _scholarshipportal_source(db)
    monkeypatch.setattr(worker_module, "fetch_scholarshipportal", _always_raises)
    monkeypatch.setattr(worker_module, "fetch_phdscanner", lambda destination, **kw: [])

    await _harvest_parsebot(db)

    await db.refresh(source)
    assert source.consecutive_harvest_failures == 1
    assert source.last_harvest_failure_at is not None


async def test_repeated_failures_accumulate_across_runs(db, monkeypatch) -> None:
    source = await _scholarshipportal_source(db)
    monkeypatch.setattr(worker_module, "fetch_scholarshipportal", _always_raises)
    monkeypatch.setattr(worker_module, "fetch_phdscanner", lambda destination, **kw: [])

    await _harvest_parsebot(db)
    await _harvest_parsebot(db)

    await db.refresh(source)
    assert source.consecutive_harvest_failures == 2


async def test_a_success_resets_the_counter(db, monkeypatch) -> None:
    source = await _scholarshipportal_source(db)
    monkeypatch.setattr(worker_module, "fetch_scholarshipportal", _always_raises)
    monkeypatch.setattr(worker_module, "fetch_phdscanner", lambda destination, **kw: [])
    await _harvest_parsebot(db)
    await db.refresh(source)
    assert source.consecutive_harvest_failures >= 1

    monkeypatch.setattr(worker_module, "fetch_scholarshipportal", _always_empty)
    await _harvest_parsebot(db)

    await db.refresh(source)
    assert source.consecutive_harvest_failures == 0


def test_update_harvest_health_ignores_a_run_with_no_attempts() -> None:
    source = Source(
        name="X", source_type="parsebot_api", authority_grade="C", approved_domains=["x.test"]
    )
    source.consecutive_harvest_failures = 2
    _update_harvest_health(source, attempts=0, failures=0, now=datetime.now(UTC))
    assert source.consecutive_harvest_failures == 2
