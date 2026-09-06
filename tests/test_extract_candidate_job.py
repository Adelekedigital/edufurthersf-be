"""The extract_candidate worker job - previously listed as an allowed
QStash job kind with no handler at all, so any delivery for it failed with
"No worker handler for extract_candidate"."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.domain.ai_router import AIRouterOutcome, AIRouterResponse
from app.domain.models import Discovery, Source, SourcePage
from app.infra import worker as worker_module
from app.infra.jobs import enqueue_job
from app.infra.worker import execute_job
from tests.conftest import requires_db

pytestmark = requires_db


@dataclass(frozen=True)
class _FakeSettings:
    ai_router_base_url: str | None
    ai_router_private_key_pem: str | None
    ai_router_key_id: str | None


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
    # No AI Router configured in tests by default - never fabricate a result.
    assert discovery.ai_extracted_facts is None


async def test_ai_router_unconfigured_leaves_ai_extracted_facts_null(db, monkeypatch) -> None:
    monkeypatch.setattr(
        worker_module,
        "get_settings",
        lambda: _FakeSettings(None, None, None),
    )
    discovery = await _discovery(db, raw_title="Award A", raw_excerpt="details")
    job, _ = await enqueue_job(
        db, "extract_candidate", f"extract:{discovery.discovery_id}",
        {"discovery_id": str(discovery.discovery_id)},
    )
    assert await execute_job(db, job.job_id) == "completed"
    await db.refresh(discovery)
    assert discovery.ai_extracted_facts is None


async def test_ai_router_completed_outcome_populates_ai_extracted_facts(db, monkeypatch) -> None:
    monkeypatch.setattr(
        worker_module,
        "get_settings",
        lambda: _FakeSettings("https://router.test", "fake-pem", "kid-1"),
    )

    async def _fake_execute(self, request):
        return AIRouterResponse(
            request_id="req-1",
            outcome=AIRouterOutcome.completed,
            output={"field": "ict"},
            model_policy_version="v1",
            trace_reference=None,
        )

    monkeypatch.setattr(worker_module.AIRouterClient, "execute", _fake_execute)
    discovery = await _discovery(db, raw_title="Award B", raw_excerpt="details")
    job, _ = await enqueue_job(
        db, "extract_candidate", f"extract:{discovery.discovery_id}",
        {"discovery_id": str(discovery.discovery_id)},
    )
    assert await execute_job(db, job.job_id) == "completed"
    await db.refresh(discovery)
    assert discovery.ai_extracted_facts == {"field": "ict"}


async def test_ai_router_non_completed_outcome_leaves_ai_extracted_facts_null(
    db, monkeypatch
) -> None:
    """review/budget_exhausted/provider_unavailable all mean "no result yet" -
    never something extract_candidate stores as if it were usable output."""
    monkeypatch.setattr(
        worker_module,
        "get_settings",
        lambda: _FakeSettings("https://router.test", "fake-pem", "kid-1"),
    )

    async def _fake_execute(self, request):
        return AIRouterResponse(
            request_id="req-1",
            outcome=AIRouterOutcome.provider_unavailable,
            output=None,
            model_policy_version=None,
            trace_reference=None,
        )

    monkeypatch.setattr(worker_module.AIRouterClient, "execute", _fake_execute)
    discovery = await _discovery(db, raw_title="Award C", raw_excerpt="details")
    job, _ = await enqueue_job(
        db, "extract_candidate", f"extract:{discovery.discovery_id}",
        {"discovery_id": str(discovery.discovery_id)},
    )
    assert await execute_job(db, job.job_id) == "completed"
    await db.refresh(discovery)
    assert discovery.ai_extracted_facts is None


async def test_ai_router_transport_failure_does_not_fail_extract_candidate(db, monkeypatch) -> None:
    """A network failure calling the Router must degrade to "no AI facts",
    not fail the whole extract_candidate job - the deterministic extraction
    still ran and must still be saved."""
    monkeypatch.setattr(
        worker_module,
        "get_settings",
        lambda: _FakeSettings("https://router.test", "fake-pem", "kid-1"),
    )

    async def _fake_execute(self, request):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(worker_module.AIRouterClient, "execute", _fake_execute)
    discovery = await _discovery(db, raw_title="Award D", raw_excerpt="details")
    job, _ = await enqueue_job(
        db, "extract_candidate", f"extract:{discovery.discovery_id}",
        {"discovery_id": str(discovery.discovery_id)},
    )
    assert await execute_job(db, job.job_id) == "completed"
    await db.refresh(discovery)
    assert discovery.ai_extracted_facts is None
    assert discovery.extracted_facts is not None


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
