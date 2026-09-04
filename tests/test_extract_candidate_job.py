"""The extract_candidate worker job - previously listed as an allowed
QStash job kind with no handler at all, so any delivery for it failed with
"No worker handler for extract_candidate"."""

from __future__ import annotations

from app.domain.models import Discovery, Source, SourcePage
from app.infra.jobs import enqueue_job
from app.infra.worker import execute_job
from tests.conftest import requires_db

pytestmark = requires_db


async def _discovery(db, *, raw_title: str, raw_excerpt: str) -> Discovery:
    source = Source(
        name="ScholarshipRegion",
        source_type="aggregator",
        authority_grade="C",
        approved_domains=["example.test"],
        active=True,
    )
    db.add(source)
    await db.flush()
    page = SourcePage(source_id=source.source_id, normalized_url="https://example.test/award")
    db.add(page)
    await db.flush()
    discovery = Discovery(
        source_page_id=page.page_id,
        content_hash="hash-a",
        raw_title=raw_title,
        raw_excerpt=raw_excerpt,
    )
    db.add(discovery)
    await db.commit()
    return discovery


async def test_extract_candidate_populates_the_discoverys_extracted_facts(db) -> None:
    discovery = await _discovery(
        db,
        raw_title="UCL Mathematics Scholarship",
        raw_excerpt="offers a £13,000 grant, deadline March 15, 2026, for Master's students.",
    )
    job, _ = await enqueue_job(
        db, "extract_candidate", f"extract:{discovery.discovery_id}",
        {"discovery_id": str(discovery.discovery_id)},
    )

    state = await execute_job(db, job.job_id)

    assert state == "completed"
    await db.refresh(discovery)
    assert discovery.extracted_facts["funding_mentions"] == ["£13,000"]
    assert discovery.extracted_facts["deadline_mentions"] == ["March 15, 2026"]
    assert discovery.extracted_facts["level_mentions"] == ["masters"]
    assert discovery.extracted_facts["needs_human_review"] is True


async def test_extract_candidate_for_an_unknown_discovery_fails_the_job(db) -> None:
    job, _ = await enqueue_job(
        db,
        "extract_candidate",
        "extract:missing",
        {"discovery_id": "01a06530-b2ef-7617-b74e-c22c6e4053fa"},
    )
    try:
        await execute_job(db, job.job_id)
        raised = False
    except LookupError:
        raised = True
    assert raised
