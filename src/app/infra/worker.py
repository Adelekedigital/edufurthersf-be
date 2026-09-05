import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domain.extraction import extract_candidate_facts
from app.domain.models import Discovery, ReviewTask
from app.domain.normalization import normalize_discovery
from app.domain.review_draft import draft_review_recommendation
from app.infra.core_catalogue import CoreCatalogueClient
from app.infra.countries import load_vocabulary, sync_countries
from app.infra.jobs import (
    claim_job_for_execution,
    complete_job,
    fail_job_for_execution,
    reconcile_stuck_jobs,
)
from app.infra.linking import link_discovery
from app.infra.outbox import dispatch_analytics_events
from app.infra.source_persistence import fetch_and_persist_page


async def execute_job(db: AsyncSession, job_id: uuid.UUID) -> str:
    """Claim and execute one durable job; callers can safely retry delivery."""
    job = await claim_job_for_execution(db, job_id)
    try:
        if job.kind == "normalize_discovery":
            await _normalize_discovery(db, job.payload)
        elif job.kind == "link_canonical":
            await link_discovery(db, uuid.UUID(job.payload["discovery_id"]))
        elif job.kind == "fetch_source_page":
            await fetch_and_persist_page(db, uuid.UUID(job.payload["page_id"]))
        elif job.kind == "dispatch_outbox":
            await dispatch_analytics_events(db)
        elif job.kind == "reconcile_stuck_jobs":
            await reconcile_stuck_jobs(db)
        elif job.kind == "sync_countries":
            await _sync_countries(db)
        elif job.kind == "extract_candidate":
            await _extract_candidate(db, job.payload)
        elif job.kind == "prepare_review":
            await _prepare_review(db, job.payload)
        else:
            # Unimplemented kinds remain durable and visible rather than being
            # acknowledged as successful no-ops.
            raise ValueError(f"No worker handler for {job.kind}")
        await complete_job(db, job)
        return job.state
    except Exception as exc:
        await fail_job_for_execution(db, job, str(exc))
        raise


async def _normalize_discovery(db: AsyncSession, payload: dict) -> None:
    discovery = await db.scalar(
        select(Discovery)
        .where(Discovery.discovery_id == uuid.UUID(payload["discovery_id"]))
        .with_for_update()
    )
    if discovery is None:
        raise LookupError("Discovery not found")
    normalized = normalize_discovery(discovery.raw_title or "")
    discovery.normalized_identity_key = normalized.identity_key
    discovery.processing_state = "normalized"
    await db.commit()


async def _sync_countries(db: AsyncSession) -> None:
    """Refresh the country mirror from Core's public catalogue."""
    settings = get_settings()
    if not settings.core_base_url:
        raise ValueError("CORE_BASE_URL is not configured")
    await sync_countries(db, CoreCatalogueClient(settings.core_base_url))


async def _extract_candidate(db: AsyncSession, payload: dict) -> None:
    discovery = await db.scalar(
        select(Discovery)
        .where(Discovery.discovery_id == uuid.UUID(payload["discovery_id"]))
        .with_for_update()
    )
    if discovery is None:
        raise LookupError("Discovery not found")
    discovery.extracted_facts = extract_candidate_facts(discovery.raw_title, discovery.raw_excerpt)
    await db.commit()


async def _prepare_review(db: AsyncSession, payload: dict) -> None:
    review_task = await db.scalar(
        select(ReviewTask)
        .where(ReviewTask.review_task_id == uuid.UUID(payload["review_task_id"]))
        .with_for_update()
    )
    if review_task is None:
        raise LookupError("Review task not found")
    if review_task.discovery_id is None:
        # ReviewTask.discovery_id is nullable for a revision-linked task with
        # no single discovery of its own; nothing here can draft a
        # destination screen without one.
        return
    discovery = await db.scalar(
        select(Discovery).where(Discovery.discovery_id == review_task.discovery_id)
    )
    if discovery is None:
        raise LookupError("Discovery not found")
    vocabulary = await load_vocabulary(db)
    review_task.draft_recommendation = draft_review_recommendation(
        raw_title=discovery.raw_title,
        raw_excerpt=discovery.raw_excerpt,
        extracted_facts=discovery.extracted_facts,
        country_names=vocabulary.names,
    )
    await db.commit()
