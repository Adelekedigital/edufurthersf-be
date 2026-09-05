import asyncio
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from pydantic import HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ingestion_schemas import FeedRecord
from app.core.config import get_settings
from app.domain.countries import SUPPORTED_DESTINATIONS
from app.domain.extraction import extract_candidate_facts
from app.domain.models import Discovery, ReviewTask, Source
from app.domain.normalization import normalize_discovery
from app.domain.parsebot_harvest import (
    PHDSCANNER_SOURCE_NAME,
    SCHOLARSHIPPORTAL_SOURCE_NAME,
    HarvestedRecord,
    opportunity_to_record,
    scholarship_to_record,
)
from app.domain.review_draft import draft_review_recommendation
from app.infra.core_catalogue import CoreCatalogueClient
from app.infra.countries import load_vocabulary, sync_countries
from app.infra.ingestion import import_feed_records
from app.infra.jobs import (
    claim_job_for_execution,
    complete_job,
    fail_job_for_execution,
    reconcile_stuck_jobs,
)
from app.infra.linking import link_discovery
from app.infra.outbox import dispatch_analytics_events
from app.infra.parsebot_client import fetch_phdscanner, fetch_scholarshipportal
from app.infra.source_persistence import fetch_and_persist_page

logger = logging.getLogger("app.infra.worker")


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
        elif job.kind == "harvest_parsebot":
            await _harvest_parsebot(db)
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


def _map_and_append(
    records: list[FeedRecord],
    *,
    source_id: uuid.UUID,
    raw: dict,
    to_record: Callable[..., HarvestedRecord | None],
    harvested_at: datetime,
) -> bool:
    """Map one raw item and append it as a `FeedRecord`, or skip it.

    Both the mapping call itself (e.g. an out-of-range `created_at` timestamp
    raising inside `datetime.fromtimestamp`) and `HttpUrl`/`FeedRecord`'s own
    field validation (title length, URL shape) can fail on a single malformed
    item from either API - that must skip just this one record, not raise out
    of the harvest loop and discard every other already-fetched destination's
    results for the week.
    """
    try:
        mapped = to_record(raw, harvested_at=harvested_at)
        if mapped is None:
            return False
        records.append(
            FeedRecord(
                source_id=source_id,
                url=HttpUrl(mapped.url),
                title=mapped.title,
                excerpt=mapped.excerpt,
                feed_created_at=mapped.feed_created_at,
            )
        )
        return True
    except (ValueError, OverflowError, OSError):
        return False


async def _harvest_parsebot(db: AsyncSession) -> None:
    """Pull new candidates from ScholarshipPortal and PhDScanner (Parse.bot).

    The kill switch is `Source.active`, not an env flag: deactivating either
    Source via the existing `POST /internal/admin/sources/{id}/deactivate`
    stops that API's harvest immediately, no redeploy needed, and
    `import_feed_records` already quarantines anything against an inactive
    source - this is belt-and-suspenders with the check below, which skips
    the network call entirely rather than paying for it and discarding the
    result.

    The Parse SDK's own client is synchronous (`httpx.Client`, not
    `AsyncClient`) - calling it directly here would block the whole process's
    single event loop, including search traffic and other jobs, for the
    entire run. `asyncio.to_thread` offloads each call to a worker thread,
    matching how every other network-calling infra module in this codebase
    stays non-blocking.

    A single destination/level's fetch failing (rate limit, upstream error -
    both real per-call failure modes per `parse_apis/CLAUDE.md`) is logged
    and skipped rather than aborting the run: a partial weekly harvest is
    worth far more than losing every already-fetched destination because one
    later call failed.
    """
    scholarshipportal = await db.scalar(
        select(Source).where(
            Source.name == SCHOLARSHIPPORTAL_SOURCE_NAME, Source.active.is_(True)
        )
    )
    phdscanner = await db.scalar(
        select(Source).where(Source.name == PHDSCANNER_SOURCE_NAME, Source.active.is_(True))
    )
    if scholarshipportal is None and phdscanner is None:
        logger.info("parsebot_harvest_skipped", extra={"reason": "no_active_source"})
        return

    harvested_at = datetime.now(UTC)
    records: list[FeedRecord] = []
    skipped = 0

    study_levels: tuple[Literal["master", "phd"], ...] = ("master", "phd")
    if scholarshipportal is not None:
        for destination in sorted(SUPPORTED_DESTINATIONS):
            for study_level in study_levels:
                try:
                    raw_items = await asyncio.to_thread(
                        fetch_scholarshipportal, destination, study_level
                    )
                except Exception:
                    logger.warning(
                        "parsebot_fetch_failed",
                        extra={
                            "api": "scholarshipportal",
                            "destination": destination,
                            "study_level": study_level,
                        },
                    )
                    continue
                for raw in raw_items:
                    appended = _map_and_append(
                        records,
                        source_id=scholarshipportal.source_id,
                        raw=raw,
                        to_record=scholarship_to_record,
                        harvested_at=harvested_at,
                    )
                    skipped += not appended

    if phdscanner is not None:
        for destination in sorted(SUPPORTED_DESTINATIONS):
            try:
                raw_items = await asyncio.to_thread(fetch_phdscanner, destination)
            except Exception:
                logger.warning(
                    "parsebot_fetch_failed", extra={"api": "phdscanner", "destination": destination}
                )
                continue
            for raw in raw_items:
                appended = _map_and_append(
                    records,
                    source_id=phdscanner.source_id,
                    raw=raw,
                    to_record=opportunity_to_record,
                    harvested_at=harvested_at,
                )
                skipped += not appended

    if not records:
        logger.info("parsebot_harvest_empty", extra={"skipped": skipped})
        return

    outcome = await import_feed_records(db, records)
    logger.info(
        "parsebot_harvest_completed",
        extra={
            "skipped": skipped,
            "imported": outcome.imported,
            "repeated": outcome.repeated,
            "changed": outcome.changed,
            "rejected": outcome.rejected,
        },
    )
