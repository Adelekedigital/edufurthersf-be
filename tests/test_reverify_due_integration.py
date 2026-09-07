"""`reverify_due`: actual re-fetch + deterministic hash recheck.

`fetch_source` is monkeypatched at its import site in
`source_persistence.py` rather than mocked at the httpx layer - real DNS
resolution (`_is_public_host`) isn't something a test should depend on, and
this job's own logic (hash comparison, defer/renew/flag) is what's under
test here, not `fetch_source`'s SSRF boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.domain.models import (
    Provider,
    PublicStatus,
    RecordState,
    ReviewTask,
    Scholarship,
    ScholarshipCycle,
    Source,
)
from app.infra import freshness as freshness_module
from app.infra import source_persistence as source_persistence_module
from app.infra.freshness import OFFICIAL_SOURCE_NAME, reverify_due_cycles
from app.infra.source_fetch import FetchedSource
from tests.conftest import requires_db

pytestmark = requires_db

NOW = datetime.now(UTC)


async def _official_source(db) -> Source:
    source = Source(
        name=OFFICIAL_SOURCE_NAME,
        source_type="official_direct",
        authority_grade="A",
        approved_domains=["unused.invalid"],
        active=True,
    )
    db.add(source)
    await db.commit()
    return source


async def _publish(
    db,
    *,
    slug: str = "award-a",
    last_verified_at: datetime | None = None,
    created_at: datetime | None = None,
    public_status: PublicStatus = PublicStatus.open_verified,
) -> ScholarshipCycle:
    provider = Provider(name="Example University", approved_domains=["example.test"])
    db.add(provider)
    await db.flush()
    scholarship = Scholarship(
        provider_id=provider.provider_id,
        slug=slug,
        name="Award A",
        official_home_url="https://example.test/award",
        award_type="scholarship",
        lifecycle_state=RecordState.published,
    )
    db.add(scholarship)
    await db.flush()
    cycle = ScholarshipCycle(
        scholarship_id=scholarship.scholarship_id,
        provider_cycle_key=f"{slug}-2026",
        official_cycle_url=f"https://example.test/{slug}/apply",
        public_status=public_status,
        facts={},
        last_verified_at=last_verified_at,
    )
    db.add(cycle)
    await db.commit()
    await db.refresh(cycle)
    if created_at is not None:
        cycle.created_at = created_at
        await db.commit()
        await db.refresh(cycle)
    return cycle


def _stub_fetch(monkeypatch, *, content: bytes = b"same content", status_code: int = 200):
    async def _fake(url, approved_domains, *, max_bytes=2_000_000):
        return FetchedSource(
            url=url, status_code=status_code, content=content, content_type="text/html"
        )

    monkeypatch.setattr(source_persistence_module, "fetch_source", _fake)


def _stub_fetch_raises(monkeypatch, exc: Exception):
    async def _fake(url, approved_domains, *, max_bytes=2_000_000):
        raise exc

    monkeypatch.setattr(source_persistence_module, "fetch_source", _fake)


async def test_missing_official_source_is_a_graceful_no_op(db, monkeypatch) -> None:
    await _publish(db, last_verified_at=None, created_at=NOW)
    _stub_fetch(monkeypatch)
    result = await reverify_due_cycles(db)
    assert result == {"checked": 0, "renewed": 0, "flagged": 0, "deferred": 0}


async def test_first_ever_fetch_defers_when_not_yet_overdue(db, monkeypatch) -> None:
    await _official_source(db)
    await _publish(db, last_verified_at=None, created_at=NOW)
    _stub_fetch(monkeypatch)

    result = await reverify_due_cycles(db)
    assert result == {"checked": 1, "renewed": 0, "flagged": 0, "deferred": 1}
    assert list(await db.scalars(select(ReviewTask))) == []


async def test_unchanged_hash_on_a_second_fetch_renews(db, monkeypatch) -> None:
    await _official_source(db)
    cycle = await _publish(db, last_verified_at=None, created_at=NOW)
    _stub_fetch(monkeypatch, content=b"same content")

    first = await reverify_due_cycles(db)
    assert first["deferred"] == 1

    second = await reverify_due_cycles(db)
    assert second == {"checked": 1, "renewed": 1, "flagged": 0, "deferred": 0}
    await db.refresh(cycle)
    assert cycle.last_verified_at is not None


async def test_changed_hash_opens_a_review_task(db, monkeypatch) -> None:
    await _official_source(db)
    cycle = await _publish(db, last_verified_at=None, created_at=NOW)
    _stub_fetch(monkeypatch, content=b"version one")
    first = await reverify_due_cycles(db)
    assert first["deferred"] == 1

    _stub_fetch(monkeypatch, content=b"version two - completely different")
    second = await reverify_due_cycles(db)
    assert second == {"checked": 1, "renewed": 0, "flagged": 1, "deferred": 0}

    tasks = list(await db.scalars(select(ReviewTask)))
    assert len(tasks) == 1
    assert tasks[0].cycle_id == cycle.cycle_id
    assert tasks[0].reason == "reverify_content_changed"
    assert tasks[0].draft_recommendation["previous_content_hash"] is not None


async def test_a_single_fetch_failure_defers_rather_than_flags(db, monkeypatch) -> None:
    await _official_source(db)
    # rolling_open: due after 24h (fetch_interval), not yet stale until 48h
    # (max_evidence_age) - past the first, comfortably inside the second.
    await _publish(db, last_verified_at=NOW - timedelta(hours=25), created_at=NOW)
    _stub_fetch_raises(monkeypatch, ValueError("Source URL domain is not approved"))

    result = await reverify_due_cycles(db)
    assert result == {"checked": 1, "renewed": 0, "flagged": 0, "deferred": 1}
    assert list(await db.scalars(select(ReviewTask))) == []


async def test_repeated_failure_past_the_evidence_window_flags(db, monkeypatch) -> None:
    """rolling_open's default max_evidence_age is 48h; created_at long
    enough ago with no successful confirmation must escalate."""
    await _official_source(db)
    cycle = await _publish(
        db, last_verified_at=None, created_at=NOW - timedelta(hours=72)
    )
    _stub_fetch_raises(monkeypatch, ValueError("boom"))

    result = await reverify_due_cycles(db)
    assert result == {"checked": 1, "renewed": 0, "flagged": 1, "deferred": 0}
    tasks = list(await db.scalars(select(ReviewTask)))
    assert len(tasks) == 1
    assert tasks[0].cycle_id == cycle.cycle_id
    assert tasks[0].reason == "reverify_fetch_failed"


async def test_a_cycle_not_yet_due_is_skipped(db, monkeypatch) -> None:
    await _official_source(db)
    await _publish(db, last_verified_at=NOW - timedelta(minutes=5), created_at=NOW)
    _stub_fetch(monkeypatch)

    result = await reverify_due_cycles(db)
    assert result == {"checked": 0, "renewed": 0, "flagged": 0, "deferred": 0}


async def test_overlapping_runs_do_not_duplicate_the_review_task(db, monkeypatch) -> None:
    """Simulates two overlapping sweeps both trying to flag the same cycle -
    uq_review_tasks_open_per_cycle (migration 0021) must hold."""
    await _official_source(db)
    cycle = await _publish(db, last_verified_at=None, created_at=NOW)
    _stub_fetch(monkeypatch, content=b"version one")
    await reverify_due_cycles(db)  # establishes the baseline hash

    _stub_fetch(monkeypatch, content=b"version two")
    await reverify_due_cycles(db)
    await reverify_due_cycles(db)  # a second overlapping tick, same changed content

    tasks = list(
        await db.scalars(select(ReviewTask).where(ReviewTask.cycle_id == cycle.cycle_id))
    )
    assert len(tasks) == 1


async def test_batch_limit_bounds_how_many_due_cycles_one_tick_processes(db, monkeypatch) -> None:
    await _official_source(db)
    for i in range(3):
        await _publish(db, slug=f"award-{i}", last_verified_at=None, created_at=NOW)
    _stub_fetch(monkeypatch)

    result = await reverify_due_cycles(db, limit=2)
    assert result["checked"] == 2


async def test_an_unexpected_error_on_one_cycle_does_not_abort_the_sweep(db, monkeypatch) -> None:
    """A genuinely unexpected error (not an ordinary fetch failure, which
    _reverify_one_cycle already handles internally) must still let the
    sweep move on to the next cycle rather than losing the whole tick."""
    await _official_source(db)
    broken = await _publish(db, slug="broken", last_verified_at=None, created_at=NOW)
    healthy = await _publish(db, slug="healthy", last_verified_at=None, created_at=NOW)
    _stub_fetch(monkeypatch)

    original_canonicalize = freshness_module.canonicalize_url

    def _flaky_canonicalize(url):
        if "broken" in url:
            raise RuntimeError("unexpected failure")
        return original_canonicalize(url)

    monkeypatch.setattr(freshness_module, "canonicalize_url", _flaky_canonicalize)

    result = await reverify_due_cycles(db)
    assert result["checked"] == 2
    assert result["deferred"] == 1  # only the healthy cycle completed successfully
    await db.refresh(broken)
    await db.refresh(healthy)
    assert broken.source_page_id is None


def test_freshness_config_reads_every_configured_field() -> None:
    """Guards _freshness_config against silently dropping a field if the
    dataclass gains one without config.py or this mapping being updated."""
    from app.core.config import get_settings

    cfg = freshness_module._freshness_config(get_settings())
    assert cfg.open_far_fetch_hours == get_settings().freshness_open_far_fetch_hours
