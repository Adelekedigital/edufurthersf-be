"""gather_corroboration against real linked/duplicate discoveries."""

from __future__ import annotations

from sqlalchemy import select

from app.api.ingestion_schemas import FeedRecord
from app.domain.linking import LinkOutcome
from app.domain.models import Discovery, Source
from app.infra.corroboration import gather_corroboration
from app.infra.ingestion import import_feed_records
from app.infra.linking import link_discovery
from tests.conftest import requires_db

pytestmark = requires_db


async def _source(db, *, name: str) -> Source:
    source = Source(
        name=name,
        source_type="aggregator",
        authority_grade="C",
        approved_domains=["example.test"],
        active=True,
    )
    db.add(source)
    await db.commit()
    return source


def _record(source_id, url: str, title: str, excerpt: str) -> FeedRecord:
    return FeedRecord(source_id=source_id, url=url, title=title, excerpt=excerpt)


async def test_two_sources_reporting_the_same_amount_corroborate_each_other(db) -> None:
    first_source = await _source(db, name="ScholarshipRegion")
    second_source = await _source(db, name="Tavily Web Search")
    await import_feed_records(
        db,
        [_record(first_source.source_id, "https://example.test/a", "Award A", "£13,000 grant.")],
    )
    await import_feed_records(
        db,
        [_record(second_source.source_id, "https://example.test/a2", "Award A", "£13,000 grant.")],
    )
    discoveries = list(await db.scalars(select(Discovery).order_by(Discovery.created_at)))
    first, second = discoveries

    assert await link_discovery(db, first.discovery_id) == LinkOutcome.new_candidate
    assert await link_discovery(db, second.discovery_id) == LinkOutcome.duplicate_pending
    await db.refresh(first)

    result = await gather_corroboration(db, first)

    assert result.independent_source_count == 2
    assert result.amount_corroborated is True
    assert result.corroborating_discovery_ids == [str(second.discovery_id)]


async def test_conflicting_amounts_do_not_corroborate(db) -> None:
    first_source = await _source(db, name="ScholarshipRegion")
    second_source = await _source(db, name="Tavily Web Search")
    await import_feed_records(
        db,
        [_record(first_source.source_id, "https://example.test/a", "Award B", "£13,000 grant.")],
    )
    await import_feed_records(
        db,
        [_record(second_source.source_id, "https://example.test/a2", "Award B", "£16,750 grant.")],
    )
    discoveries = list(await db.scalars(select(Discovery).order_by(Discovery.created_at)))
    first, _second = discoveries

    assert await link_discovery(db, first.discovery_id) == LinkOutcome.new_candidate
    assert await link_discovery(db, _second.discovery_id) == LinkOutcome.duplicate_pending
    await db.refresh(first)

    result = await gather_corroboration(db, first)

    assert result.independent_source_count == 2
    assert result.amount_corroborated is False


async def test_a_solo_discovery_has_no_corroboration(db) -> None:
    source = await _source(db, name="ScholarshipRegion")
    await import_feed_records(
        db, [_record(source.source_id, "https://example.test/solo", "Award C", "£13,000 grant.")]
    )
    discovery = await db.scalar(select(Discovery))

    assert await link_discovery(db, discovery.discovery_id) == LinkOutcome.new_candidate
    await db.refresh(discovery)

    result = await gather_corroboration(db, discovery)

    assert result.independent_source_count == 1
    assert result.amount_corroborated is False
    assert result.deadline_corroborated is None
