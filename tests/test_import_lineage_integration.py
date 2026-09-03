"""The Sheet import contract: five columns, run lineage, and quarantine.

A row that fails to become a Discovery must survive as data, not disappear
into a counter; a repeated URL must be traceable; and a changed row must
supersede the old one rather than erase it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.api.ingestion_schemas import FeedRecord
from app.domain.models import (
    CrawlRun,
    Discovery,
    DiscoveryQuarantine,
    ProcessingJob,
    Source,
    SourcePage,
)
from app.infra.ingestion import import_feed_records
from tests.conftest import requires_db

pytestmark = requires_db


async def _source(db, *, active: bool = True) -> Source:
    source = Source(
        name="ScholarshipRegion",
        source_type="aggregator",
        authority_grade="C",
        approved_domains=["example.test"],
        active=active,
    )
    db.add(source)
    await db.commit()
    return source


def _record(source_id, url: str, title: str, **overrides) -> FeedRecord:
    return FeedRecord(source_id=source_id, url=url, title=title, excerpt="An award", **overrides)


async def test_the_feeds_own_dates_are_carried_through_unchanged(db) -> None:
    """Source Posted Date / Created Date are discovery signals, not deadlines."""
    source = await _source(db)
    posted = datetime(2026, 1, 5, tzinfo=UTC)
    created = datetime(2026, 1, 6, tzinfo=UTC)
    await import_feed_records(
        db,
        [
            _record(
                source.source_id,
                "https://example.test/a",
                "Award A",
                source_posted_at=posted,
                feed_created_at=created,
            )
        ],
    )
    discovery = await db.scalar(select(Discovery))
    assert discovery.source_posted_at == posted
    assert discovery.feed_created_at == created


async def test_every_import_creates_a_crawl_run_with_final_counts(db) -> None:
    source = await _source(db)
    outcome = await import_feed_records(
        db,
        [
            _record(source.source_id, "https://example.test/a", "Award A"),
            _record(source.source_id, "https://example.test/a", "Award A"),
            _record(uuid.uuid4(), "https://example.test/z", "Unknown"),
        ],
    )
    run = await db.scalar(select(CrawlRun).where(CrawlRun.crawl_run_id == outcome.crawl_run_id))
    assert run.kind == "import_feed"
    assert run.state == "completed"
    assert run.finished_at is not None
    assert (run.imported_count, run.repeated_count, run.rejected_count) == (1, 1, 1)
    assert run.scope["record_count"] == 3


async def test_processing_jobs_carry_the_crawl_run_as_correlation(db) -> None:
    source = await _source(db)
    outcome = await import_feed_records(
        db, [_record(source.source_id, "https://example.test/a", "Award A")]
    )
    job = await db.scalar(select(ProcessingJob))
    assert job.correlation_id == str(outcome.crawl_run_id)


async def test_an_invalid_url_is_quarantined_not_dropped(db) -> None:
    """A row that cannot even canonicalize must still be retrievable."""
    source = await _source(db)
    # FastAPI's HttpUrl gate would refuse a non-http(s) scheme before this ever
    # runs; model_construct skips validation so the domain layer's own guard,
    # not just the API boundary, is what is under test here.
    record = FeedRecord.model_construct(
        source_id=source.source_id,
        url="ftp://example.test/not-http",
        title="Broken",
        excerpt=None,
        source_posted_at=None,
        feed_created_at=None,
    )

    outcome = await import_feed_records(db, [record])
    assert outcome.rejected == 1
    row = await db.scalar(select(DiscoveryQuarantine))
    assert row.reason == "invalid_url"
    assert row.raw_title == "Broken"
    assert row.crawl_run_id == outcome.crawl_run_id


async def test_an_unknown_source_is_quarantined_with_its_source_id(db) -> None:
    missing_source_id = uuid.uuid4()
    outcome = await import_feed_records(
        db, [_record(missing_source_id, "https://example.test/a", "Award A")]
    )
    assert outcome.rejected == 1
    row = await db.scalar(select(DiscoveryQuarantine))
    assert row.reason == "unknown_or_inactive_source"
    assert row.source_id == missing_source_id
    assert row.raw_url == "https://example.test/a"


async def test_an_inactive_source_is_quarantined(db) -> None:
    source = await _source(db, active=False)
    outcome = await import_feed_records(
        db, [_record(source.source_id, "https://example.test/a", "Award A")]
    )
    assert outcome.rejected == 1
    row = await db.scalar(select(DiscoveryQuarantine))
    assert row.reason == "unknown_or_inactive_source"


async def test_a_repeated_url_updates_last_seen_at(db) -> None:
    source = await _source(db)
    await import_feed_records(db, [_record(source.source_id, "https://example.test/a", "Award A")])
    page = await db.scalar(select(SourcePage))
    first_seen = page.last_seen_at
    assert first_seen is not None

    await import_feed_records(db, [_record(source.source_id, "https://example.test/a", "Award A")])
    await db.refresh(page)
    assert page.last_seen_at >= first_seen


async def test_changed_content_supersedes_the_previous_discovery_without_deleting_it(db) -> None:
    """A meaningfully changed re-crawl creates a new revision; the old one stays."""
    source = await _source(db)
    await import_feed_records(db, [_record(source.source_id, "https://example.test/a", "Award A")])
    original = await db.scalar(select(Discovery))

    outcome = await import_feed_records(
        db, [_record(source.source_id, "https://example.test/a", "Award A - Updated Deadline")]
    )
    assert (outcome.imported, outcome.repeated, outcome.changed) == (0, 0, 1)

    rows = list(await db.scalars(select(Discovery)))
    assert len(rows) == 2, "the earlier discovery must not be deleted or overwritten"
    newest = next(row for row in rows if row.discovery_id != original.discovery_id)
    assert newest.supersedes_discovery_id == original.discovery_id
    # The original is still queryable with its original content.
    assert original.raw_title == "Award A"
    assert newest.raw_title == "Award A - Updated Deadline"


async def test_a_third_revision_chains_to_the_second_not_the_first(db) -> None:
    source = await _source(db)
    await import_feed_records(db, [_record(source.source_id, "https://example.test/a", "v1")])
    first = await db.scalar(select(Discovery))
    await import_feed_records(db, [_record(source.source_id, "https://example.test/a", "v2")])
    second = await db.scalar(
        select(Discovery).where(Discovery.supersedes_discovery_id == first.discovery_id)
    )
    await import_feed_records(db, [_record(source.source_id, "https://example.test/a", "v3")])
    third = await db.scalar(
        select(Discovery).where(Discovery.supersedes_discovery_id == second.discovery_id)
    )
    assert third is not None
    assert third.raw_title == "v3"


async def test_rejected_rows_do_not_prevent_valid_rows_in_the_same_batch(db) -> None:
    source = await _source(db)
    outcome = await import_feed_records(
        db,
        [
            _record(uuid.uuid4(), "https://example.test/bad", "Bad"),
            _record(source.source_id, "https://example.test/good", "Good"),
        ],
    )
    assert (outcome.imported, outcome.rejected) == (1, 1)
