"""link_discovery populates extracted_facts/ai_extracted_facts and computes
a real ReviewTask.priority - closing the gap where extract_candidate was
never actually enqueued by the ingestion pipeline (nothing called it
automatically before this), and never wastes an extraction call on an
outcome that never surfaces facts to a reviewer."""

from __future__ import annotations

from sqlalchemy import select

from app.api.ingestion_schemas import FeedRecord
from app.domain.linking import LinkOutcome
from app.domain.models import Discovery, Provider, ReviewTask, Scholarship, Source
from app.domain.review_priority import NEEDS_REVIEW_BASE, NEW_CANDIDATE_BASE
from app.infra.ingestion import import_feed_records
from app.infra.linking import link_discovery
from tests.conftest import requires_db

pytestmark = requires_db


async def _source(db, *, authority_grade: str = "C", name: str = "ScholarshipRegion") -> Source:
    source = Source(
        name=name,
        source_type="aggregator",
        authority_grade=authority_grade,
        approved_domains=["example.test"],
        active=True,
    )
    db.add(source)
    await db.commit()
    return source


def _record(source_id, url: str, title: str, excerpt: str) -> FeedRecord:
    return FeedRecord(source_id=source_id, url=url, title=title, excerpt=excerpt)


async def test_new_candidate_populates_extracted_facts(db) -> None:
    source = await _source(db, authority_grade="A")
    await import_feed_records(
        db,
        [
            _record(
                source.source_id,
                "https://example.test/a",
                "Award A",
                "Offers a £13,000 grant, deadline 1 March 2027, for Master's students.",
            )
        ],
    )
    discovery = await db.scalar(select(Discovery))

    assert await link_discovery(db, discovery.discovery_id) == LinkOutcome.new_candidate

    await db.refresh(discovery)
    assert discovery.extracted_facts is not None
    assert discovery.extracted_facts["funding_mentions"] == ["£13,000"]
    # No AI Router configured in tests by default - never fabricate a result.
    assert discovery.ai_extracted_facts is None


async def test_a_complete_tier_a_candidate_outranks_a_thin_tier_c_one(db) -> None:
    strong_source = await _source(db, authority_grade="A", name="DAAD Scholarship Database")
    weak_source = await _source(db, authority_grade="C", name="ScholarshipRegion")
    await import_feed_records(
        db,
        [
            _record(
                strong_source.source_id,
                "https://example.test/strong",
                "Strong Award",
                "Offers a £13,000 grant, deadline 1 March 2027, for Master's students.",
            )
        ],
    )
    await import_feed_records(
        db, [_record(weak_source.source_id, "https://example.test/weak", "Weak Award", "")]
    )
    strong_discovery = await db.scalar(
        select(Discovery).where(Discovery.raw_title == "Strong Award")
    )
    weak_discovery = await db.scalar(select(Discovery).where(Discovery.raw_title == "Weak Award"))

    assert await link_discovery(db, strong_discovery.discovery_id) == LinkOutcome.new_candidate
    assert await link_discovery(db, weak_discovery.discovery_id) == LinkOutcome.new_candidate

    strong_task = await db.scalar(
        select(ReviewTask).where(ReviewTask.discovery_id == strong_discovery.discovery_id)
    )
    weak_task = await db.scalar(
        select(ReviewTask).where(ReviewTask.discovery_id == weak_discovery.discovery_id)
    )
    assert strong_task.priority < weak_task.priority
    assert weak_task.priority == NEW_CANDIDATE_BASE


async def test_ambiguous_link_still_uses_the_needs_review_band(db) -> None:
    source = await _source(db)
    provider = Provider(name="Provider", approved_domains=["example.test"])
    db.add(provider)
    await db.flush()
    for slug in ("one", "two"):
        db.add(
            Scholarship(
                provider_id=provider.provider_id,
                slug=slug,
                name="Award A",
                official_home_url="https://example.test/award",
                award_type="scholarship",
            )
        )
    await db.commit()
    await import_feed_records(
        db, [_record(source.source_id, "https://example.test/a", "Award A", "")]
    )
    discovery = await db.scalar(select(Discovery))

    assert await link_discovery(db, discovery.discovery_id) == LinkOutcome.needs_review

    task = await db.scalar(
        select(ReviewTask).where(ReviewTask.discovery_id == discovery.discovery_id)
    )
    assert task.priority == NEEDS_REVIEW_BASE
    await db.refresh(discovery)
    assert discovery.extracted_facts is not None


async def test_linked_outcome_never_triggers_extraction(db) -> None:
    source = await _source(db)
    provider = Provider(name="Provider", approved_domains=["example.test"])
    db.add(provider)
    await db.flush()
    db.add(
        Scholarship(
            provider_id=provider.provider_id,
            slug="award-a",
            name="Award A",
            official_home_url="https://example.test/award",
            award_type="scholarship",
        )
    )
    await db.commit()
    await import_feed_records(
        db, [_record(source.source_id, "https://example.test/a", "Award A", "")]
    )
    discovery = await db.scalar(select(Discovery))

    assert await link_discovery(db, discovery.discovery_id) == LinkOutcome.linked

    await db.refresh(discovery)
    assert discovery.extracted_facts is None


async def test_duplicate_pending_outcome_never_triggers_extraction(db) -> None:
    first_source = await _source(db, name="ScholarshipRegion")
    second_source = await _source(db, name="Tavily Web Search")
    await import_feed_records(
        db, [_record(first_source.source_id, "https://example.test/a", "Award A", "")]
    )
    await import_feed_records(
        db, [_record(second_source.source_id, "https://example.test/a2", "Award A", "")]
    )
    discoveries = list(await db.scalars(select(Discovery).order_by(Discovery.created_at)))
    first, second = discoveries

    assert await link_discovery(db, first.discovery_id) == LinkOutcome.new_candidate
    assert await link_discovery(db, second.discovery_id) == LinkOutcome.duplicate_pending

    await db.refresh(second)
    assert second.extracted_facts is None
