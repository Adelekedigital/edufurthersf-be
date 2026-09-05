"""prepare_review end to end: a new review task gets a job, the job drafts a
recommendation, and nothing here ever touches ReviewTask.state."""

from __future__ import annotations

from sqlalchemy import select

from app.api.ingestion_schemas import FeedRecord
from app.domain.linking import LinkOutcome
from app.domain.models import Discovery, ProcessingJob, ReviewTask, Source
from app.infra.ingestion import import_feed_records
from app.infra.linking import link_discovery
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


async def _discover(db, *, title: str, excerpt: str, slug: str) -> Discovery:
    source = await _source(db)
    await import_feed_records(
        db,
        [FeedRecord(source_id=source.source_id, url=f"https://example.test/{slug}",
                     title=title, excerpt=excerpt)],
    )
    return await db.scalar(select(Discovery).where(Discovery.raw_title == title))


async def test_a_new_review_task_enqueues_prepare_review(db) -> None:
    discovery = await _discover(
        db, title="Award A", excerpt="An award", slug="a"
    )
    assert await link_discovery(db, discovery.discovery_id) == LinkOutcome.new_candidate

    task = await db.scalar(
        select(ReviewTask).where(ReviewTask.discovery_id == discovery.discovery_id)
    )
    job = await db.scalar(
        select(ProcessingJob).where(
            ProcessingJob.dedupe_key == f"prepare_review:{task.review_task_id}"
        )
    )
    assert job is not None
    assert job.payload == {"review_task_id": str(task.review_task_id)}


async def test_relinking_does_not_enqueue_a_second_prepare_review_job(db) -> None:
    discovery = await _discover(
        db, title="Award B", excerpt="An award", slug="b"
    )
    assert await link_discovery(db, discovery.discovery_id) == LinkOutcome.new_candidate
    assert await link_discovery(db, discovery.discovery_id) == LinkOutcome.new_candidate

    jobs = list(
        await db.scalars(select(ProcessingJob).where(ProcessingJob.kind == "prepare_review"))
    )
    assert len(jobs) == 1


async def test_prepare_review_drafts_a_destination_reject(db) -> None:
    discovery = await _discover(
        db,
        title="University of Lagos PhD Scholarship",
        excerpt="Open to students studying in Nigeria.",
        slug="c",
    )
    await link_discovery(db, discovery.discovery_id)
    task = await db.scalar(
        select(ReviewTask).where(ReviewTask.discovery_id == discovery.discovery_id)
    )
    job = await db.scalar(
        select(ProcessingJob).where(
            ProcessingJob.dedupe_key == f"prepare_review:{task.review_task_id}"
        )
    )

    assert await execute_job(db, job.job_id) == "completed"

    await db.refresh(task)
    assert task.draft_recommendation["verdict"] == "reject"
    assert task.state == "open"
    assert task.resolution is None


async def test_prepare_review_drafts_ambiguous_when_destination_is_unclear(db) -> None:
    discovery = await _discover(
        db, title="Award D", excerpt="A generous scholarship for graduate students.", slug="d"
    )
    await link_discovery(db, discovery.discovery_id)
    task = await db.scalar(
        select(ReviewTask).where(ReviewTask.discovery_id == discovery.discovery_id)
    )
    job = await db.scalar(
        select(ProcessingJob).where(
            ProcessingJob.dedupe_key == f"prepare_review:{task.review_task_id}"
        )
    )

    await execute_job(db, job.job_id)

    await db.refresh(task)
    assert task.draft_recommendation["verdict"] == "ambiguous"


async def test_prepare_review_carries_extracted_facts_into_the_draft(db) -> None:
    discovery = await _discover(
        db, title="Award E", excerpt="A £10,000 award for a Master's student.", slug="e"
    )
    discovery.extracted_facts = {"funding_mentions": ["£10,000"], "level_mentions": ["masters"]}
    await db.commit()
    await link_discovery(db, discovery.discovery_id)
    task = await db.scalar(
        select(ReviewTask).where(ReviewTask.discovery_id == discovery.discovery_id)
    )
    job = await db.scalar(
        select(ProcessingJob).where(
            ProcessingJob.dedupe_key == f"prepare_review:{task.review_task_id}"
        )
    )

    await execute_job(db, job.job_id)

    await db.refresh(task)
    assert task.draft_recommendation["proposed_facts"] == {
        "funding_mentions": ["£10,000"],
        "level_mentions": ["masters"],
    }
