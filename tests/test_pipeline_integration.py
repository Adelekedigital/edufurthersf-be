"""Discovery to publication: import, link, review and job execution."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.api.ingestion_schemas import FeedRecord
from app.api.review_schemas import ReviewDecisionRequest
from app.domain.linking import LinkOutcome
from app.domain.models import (
    Discovery,
    ProcessingJob,
    Provider,
    ReviewTask,
    Scholarship,
    Source,
    SourcePage,
)
from app.infra.ingestion import import_feed_records
from app.infra.jobs import enqueue_job
from app.infra.linking import link_discovery
from app.infra.reviews import decide_review
from app.infra.worker import execute_job
from tests.conftest import requires_db

pytestmark = requires_db


async def _source(db) -> Source:
    source = Source(
        name="ScholarshipRegion",
        source_type="aggregator",
        authority_grade="C",
        approved_domains=["example.test"],
        active=True,
    )
    db.add(source)
    await db.commit()
    return source


def _record(source_id, url: str, title: str) -> FeedRecord:
    return FeedRecord(source_id=source_id, url=url, title=title, excerpt="An award")


async def test_import_counts_imported_repeated_and_rejected_rows(db) -> None:
    source = await _source(db)
    outcome = await import_feed_records(
        db,
        [
            _record(source.source_id, "https://example.test/a", "Award A"),
            # Same normalised URL and content: a repeat, not a second programme.
            _record(source.source_id, "https://example.test/a?utm_source=x", "Award A"),
            _record(source.source_id, "https://example.test/b", "Award B"),
            _record(uuid.uuid4(), "https://example.test/c", "Unknown source"),
        ],
    )
    assert (outcome.imported, outcome.repeated, outcome.changed, outcome.rejected) == (2, 1, 0, 1)
    assert len(list(await db.scalars(select(Discovery)))) == 2
    # Lineage is preserved: one page per distinct normalised URL.
    assert len(list(await db.scalars(select(SourcePage)))) == 2


async def test_reimport_is_non_destructive(db) -> None:
    """Re-running the feed must not duplicate discoveries or lose lineage."""
    source = await _source(db)
    records = [_record(source.source_id, "https://example.test/a", "Award A")]
    first = await import_feed_records(db, records)
    second = await import_feed_records(db, records)
    assert (first.imported, first.repeated, first.changed, first.rejected) == (1, 0, 0, 0)
    assert (second.imported, second.repeated, second.changed, second.rejected) == (0, 1, 0, 0)
    assert len(list(await db.scalars(select(Discovery)))) == 1


async def test_import_enqueues_normalisation_and_linking_for_each_discovery(db) -> None:
    """Without a link_canonical job too, nothing would ever call
    link_discovery for a freshly imported row - it would sit normalized
    forever no matter how many rows are imported."""
    source = await _source(db)
    await import_feed_records(db, [_record(source.source_id, "https://example.test/a", "Award A")])
    jobs = list(await db.scalars(select(ProcessingJob)))
    assert sorted(job.kind for job in jobs) == ["link_canonical", "normalize_discovery"]


async def test_worker_normalises_a_discovery(db) -> None:
    source = await _source(db)
    await import_feed_records(db, [_record(source.source_id, "https://example.test/a", "Award A")])
    job = await db.scalar(select(ProcessingJob))
    assert await execute_job(db, job.job_id) == "completed"
    discovery = await db.scalar(select(Discovery))
    assert discovery.processing_state == "normalized"
    await db.refresh(job)
    assert job.state == "completed"


async def test_worker_records_failure_for_an_unhandled_kind(db) -> None:
    job, created = await enqueue_job(db, "refresh_status", "dedupe-unhandled", {})
    assert created is True
    with pytest.raises(ValueError):
        await execute_job(db, job.job_id)
    await db.refresh(job)
    assert job.state == "failed_review"
    assert job.last_error


async def test_enqueue_is_idempotent_on_the_dedupe_key(db) -> None:
    first, created_first = await enqueue_job(db, "normalize_discovery", "same-key", {"n": 1})
    second, created_second = await enqueue_job(db, "normalize_discovery", "same-key", {"n": 2})
    assert created_first is True
    assert created_second is False
    assert first.job_id == second.job_id
    assert len(list(await db.scalars(select(ProcessingJob)))) == 1


async def test_ambiguous_link_opens_a_review_task_instead_of_guessing(db) -> None:
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
    await import_feed_records(db, [_record(source.source_id, "https://example.test/a", "Award A")])
    discovery = await db.scalar(select(Discovery))

    assert await link_discovery(db, discovery.discovery_id) == LinkOutcome.needs_review
    task = await db.scalar(select(ReviewTask))
    assert task is not None
    assert task.reason == "ambiguous_identity_candidates"


async def test_unmatched_discovery_becomes_a_new_candidate(db) -> None:
    """Against an empty catalogue this is the outcome nearly every discovery
    gets, so it must still reach the reviewer - new_candidate has no other
    path into the queue."""
    source = await _source(db)
    await import_feed_records(db, [_record(source.source_id, "https://example.test/a", "Award A")])
    discovery = await db.scalar(select(Discovery))
    assert await link_discovery(db, discovery.discovery_id) == LinkOutcome.new_candidate

    task = await db.scalar(
        select(ReviewTask).where(ReviewTask.discovery_id == discovery.discovery_id)
    )
    assert task is not None
    assert task.reason == "no_identity_candidate"
    assert task.state == "open"


async def test_review_approval_creates_an_unpublished_scholarship(db) -> None:
    """Approval links a canonical record; it must not publish it outright."""
    source = await _source(db)
    provider = Provider(name="Provider", approved_domains=["example.test"])
    db.add(provider)
    await db.flush()
    await import_feed_records(db, [_record(source.source_id, "https://example.test/a", "Award A")])
    discovery = await db.scalar(select(Discovery))
    task = ReviewTask(discovery_id=discovery.discovery_id, reason="new_candidate")
    db.add(task)
    await db.commit()

    scholarship_id = await decide_review(
        db,
        task.review_task_id,
        ReviewDecisionRequest(
            decision="approve",
            reason="Official evidence checked",
            provider_id=provider.provider_id,
            slug="award-a",
            official_home_url="https://example.test/award",
            canonical_name="Award A",
            award_type="scholarship",
        ),
    )
    scholarship = await db.scalar(
        select(Scholarship).where(Scholarship.scholarship_id == scholarship_id)
    )
    assert scholarship.lifecycle_state.value == "needs_review"
    await db.refresh(task)
    assert task.state == "resolved"


async def test_approval_requires_a_recognised_award_type(db) -> None:
    source = await _source(db)
    provider = Provider(name="Provider", approved_domains=["example.test"])
    db.add(provider)
    await db.flush()
    await import_feed_records(db, [_record(source.source_id, "https://example.test/a", "Award A")])
    discovery = await db.scalar(select(Discovery))
    task = ReviewTask(discovery_id=discovery.discovery_id, reason="new_candidate")
    db.add(task)
    await db.commit()
    with pytest.raises(ValueError):
        await decide_review(
            db,
            task.review_task_id,
            ReviewDecisionRequest(
                decision="approve",
                reason="Official evidence checked",
                provider_id=provider.provider_id,
                slug="award-a",
                official_home_url="https://example.test/award",
                award_type="not_a_real_type",
            ),
        )


async def test_approval_stores_the_verified_award_type(db) -> None:
    source = await _source(db)
    provider = Provider(name="Provider", approved_domains=["example.test"])
    db.add(provider)
    await db.flush()
    await import_feed_records(db, [_record(source.source_id, "https://example.test/a", "Award A")])
    discovery = await db.scalar(select(Discovery))
    task = ReviewTask(discovery_id=discovery.discovery_id, reason="new_candidate")
    db.add(task)
    await db.commit()

    scholarship_id = await decide_review(
        db,
        task.review_task_id,
        ReviewDecisionRequest(
            decision="approve",
            reason="Official evidence checked",
            provider_id=provider.provider_id,
            slug="award-a",
            official_home_url="https://example.test/award",
            award_type="assistantship",
        ),
    )
    scholarship = await db.scalar(
        select(Scholarship).where(Scholarship.scholarship_id == scholarship_id)
    )
    assert scholarship.award_type == "assistantship"


async def test_a_resolved_task_cannot_be_decided_twice(db) -> None:
    task = ReviewTask(reason="new_candidate", state="resolved")
    db.add(task)
    await db.commit()
    with pytest.raises(LookupError):
        await decide_review(
            db, task.review_task_id, ReviewDecisionRequest(decision="reject", reason="No evidence")
        )


async def test_approval_without_the_required_fields_is_refused(db) -> None:
    source = await _source(db)
    await import_feed_records(db, [_record(source.source_id, "https://example.test/a", "Award A")])
    discovery = await db.scalar(select(Discovery))
    task = ReviewTask(discovery_id=discovery.discovery_id, reason="new_candidate")
    db.add(task)
    await db.commit()
    with pytest.raises(ValueError):
        await decide_review(
            db, task.review_task_id, ReviewDecisionRequest(decision="approve", reason="Looks fine")
        )


async def test_the_full_chain_from_import_to_approval_works_unassisted(db) -> None:
    """Import, then only the jobs import itself queued, run through the same
    worker QStash would dispatch to - no test setup hand-creates a ReviewTask
    or calls link_discovery directly the way the others above deliberately do.
    This is what actually happens to a real imported row."""
    source = await _source(db)
    provider = Provider(name="Provider", approved_domains=["example.test"])
    db.add(provider)
    await db.flush()
    await import_feed_records(db, [_record(source.source_id, "https://example.test/a", "Award A")])
    discovery = await db.scalar(select(Discovery))

    for job in list(await db.scalars(select(ProcessingJob))):
        assert await execute_job(db, job.job_id) == "completed"

    task = await db.scalar(
        select(ReviewTask).where(ReviewTask.discovery_id == discovery.discovery_id)
    )
    assert task is not None, "the worker alone must be able to take a row to review"

    scholarship_id = await decide_review(
        db,
        task.review_task_id,
        ReviewDecisionRequest(
            decision="approve",
            reason="Official evidence checked",
            provider_id=provider.provider_id,
            slug="award-a",
            official_home_url="https://example.test/award",
            canonical_name="Award A",
            award_type="scholarship",
        ),
    )
    assert scholarship_id is not None


async def test_relinking_a_discovery_does_not_duplicate_its_open_review_task(db) -> None:
    source = await _source(db)
    await import_feed_records(db, [_record(source.source_id, "https://example.test/a", "Award A")])
    discovery = await db.scalar(select(Discovery))

    assert await link_discovery(db, discovery.discovery_id) == LinkOutcome.new_candidate
    assert await link_discovery(db, discovery.discovery_id) == LinkOutcome.new_candidate

    tasks = list(
        await db.scalars(
            select(ReviewTask).where(ReviewTask.discovery_id == discovery.discovery_id)
        )
    )
    assert len(tasks) == 1
