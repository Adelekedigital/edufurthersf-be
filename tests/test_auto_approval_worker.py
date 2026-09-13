"""_auto_approve_sweep - candidate selection, batching, and per-item
isolation. `attempt_auto_approval` itself is stubbed at its import site in
worker.py (already covered end to end in test_auto_approval_integration.py) -
what's under test here is the sweep's own eligibility query and loop."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.api.ingestion_schemas import FeedRecord
from app.domain.linking import LinkOutcome
from app.domain.models import Discovery, ReviewTask, Source
from app.infra import worker as worker_module
from app.infra.auto_approval import AutoApprovalOutcome
from app.infra.ingestion import import_feed_records
from app.infra.linking import link_discovery
from app.infra.worker import _auto_approve_sweep
from tests.conftest import requires_db

pytestmark = requires_db


@dataclass(frozen=True)
class _FakeSettings:
    auto_approve_enabled: bool = True
    auto_approve_min_age_hours: int = 24
    auto_approve_sweep_batch_limit: int = 50


def _configure(monkeypatch, **overrides) -> None:
    monkeypatch.setattr(worker_module, "get_settings", lambda: _FakeSettings(**overrides))


async def _old_enough_discovery(db, *, hours_old: int = 48) -> tuple[Discovery, ReviewTask]:
    source = Source(
        name="ScholarshipRegion",
        source_type="aggregator",
        authority_grade="C",
        approved_domains=["example.test"],
        active=True,
    )
    db.add(source)
    await db.commit()
    await import_feed_records(
        db,
        [FeedRecord(source_id=source.source_id, url="https://a.test/x", title="Award", excerpt="")],
    )
    discovery = await db.scalar(select(Discovery))
    assert await link_discovery(db, discovery.discovery_id) == LinkOutcome.new_candidate
    task = await db.scalar(
        select(ReviewTask).where(ReviewTask.discovery_id == discovery.discovery_id)
    )
    await db.refresh(discovery)
    discovery.created_at = datetime.now(UTC) - timedelta(hours=hours_old)
    await db.commit()
    return discovery, task


async def test_disabled_flag_never_evaluates_anything(db, monkeypatch) -> None:
    _configure(monkeypatch, auto_approve_enabled=False)

    async def _fail(*args, **kwargs):
        raise AssertionError("attempt_auto_approval should not have been called")

    monkeypatch.setattr(worker_module, "attempt_auto_approval", _fail)
    await _old_enough_discovery(db)

    result = await _auto_approve_sweep(db)

    assert result == {"evaluated": 0, "approved": 0}


async def test_an_eligible_old_enough_candidate_is_evaluated(db, monkeypatch) -> None:
    _configure(monkeypatch)

    async def _fake_approve(db, review_task_id):
        return AutoApprovalOutcome(approved=True, reason="auto_approved")

    monkeypatch.setattr(worker_module, "attempt_auto_approval", _fake_approve)
    await _old_enough_discovery(db)

    result = await _auto_approve_sweep(db)

    assert result == {"evaluated": 1, "approved": 1}


async def test_a_too_young_candidate_is_excluded_from_the_batch(db, monkeypatch) -> None:
    _configure(monkeypatch)

    async def _fail(*args, **kwargs):
        raise AssertionError("a too-young candidate should never be selected")

    monkeypatch.setattr(worker_module, "attempt_auto_approval", _fail)
    await _old_enough_discovery(db, hours_old=1)

    result = await _auto_approve_sweep(db)

    assert result == {"evaluated": 0, "approved": 0}


async def test_an_already_evaluated_discovery_is_excluded(db, monkeypatch) -> None:
    _configure(monkeypatch)

    async def _fail(*args, **kwargs):
        raise AssertionError("an already-evaluated discovery should never be re-selected")

    monkeypatch.setattr(worker_module, "attempt_auto_approval", _fail)
    discovery, _task = await _old_enough_discovery(db)
    discovery.auto_review_evaluated_at = datetime.now(UTC)
    await db.commit()

    result = await _auto_approve_sweep(db)

    assert result == {"evaluated": 0, "approved": 0}


async def test_one_failing_candidate_does_not_abort_the_batch(db, monkeypatch) -> None:
    _configure(monkeypatch)
    _first, _ = await _old_enough_discovery(db)

    source2 = Source(
        name="Tavily Web Search",
        source_type="web_search",
        authority_grade="C",
        approved_domains=["example.test"],
        active=True,
    )
    db.add(source2)
    await db.commit()
    await import_feed_records(
        db,
        [
            FeedRecord(
                source_id=source2.source_id, url="https://a.test/y", title="Second", excerpt=""
            )
        ],
    )
    second = await db.scalar(select(Discovery).where(Discovery.raw_title == "Second"))
    assert await link_discovery(db, second.discovery_id) == LinkOutcome.new_candidate
    await db.refresh(second)
    second.created_at = datetime.now(UTC) - timedelta(hours=48)
    await db.commit()

    calls: list[str] = []

    async def _flaky(db, review_task_id):
        calls.append(str(review_task_id))
        if len(calls) == 1:
            raise RuntimeError("boom")
        return AutoApprovalOutcome(approved=False, reason="test")

    monkeypatch.setattr(worker_module, "attempt_auto_approval", _flaky)

    result = await _auto_approve_sweep(db)

    assert result == {"evaluated": 2, "approved": 0}
    assert len(calls) == 2
