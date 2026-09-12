import asyncio
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

import httpx
from pydantic import HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ingestion_schemas import FeedRecord
from app.core.config import get_settings
from app.domain.ai_router import AIRouterOutcome, AIRouterRequest, AITask
from app.domain.countries import SEED_COUNTRIES, SUPPORTED_DESTINATIONS
from app.domain.extraction import extract_candidate_facts
from app.domain.models import Discovery, ReviewTask, Source
from app.domain.normalization import normalize_discovery
from app.domain.parsebot_harvest import (
    CAREERONESTOP_SOURCE_NAME,
    FASTWEB_SOURCE_NAME,
    MASTERSPORTAL_SOURCE_NAME,
    OPPORTUNITYDESK_SOURCE_NAME,
    PHDSCANNER_SOURCE_NAME,
    SCHOLARSHIPPORTAL_SOURCE_NAME,
    HarvestedRecord,
    careeronestop_to_record,
    fastweb_to_record,
    mastersportal_to_record,
    opportunity_to_record,
    opportunitydesk_to_record,
    scholarship_to_record,
)
from app.domain.review_draft import draft_review_recommendation
from app.domain.tavily_harvest import TAVILY_SOURCE_NAME, tavily_result_to_record
from app.infra.ai_router_client import AIRouterClient
from app.infra.core_catalogue import CoreCatalogueClient
from app.infra.countries import load_vocabulary, sync_countries
from app.infra.freshness import refresh_due_statuses, reverify_due_cycles
from app.infra.ingestion import import_feed_records
from app.infra.jobs import (
    claim_job_for_execution,
    complete_job,
    due_jobs,
    fail_job_for_execution,
    reconcile_stuck_jobs,
)
from app.infra.linking import link_discovery
from app.infra.outbox import dispatch_analytics_events
from app.infra.parsebot_client import (
    Major,
    fetch_careeronestop,
    fetch_fastweb_by_major,
    fetch_fastweb_featured,
    fetch_mastersportal,
    fetch_opportunitydesk,
    fetch_phdscanner,
    fetch_scholarshipportal,
)
from app.infra.research_budget import reserve_call
from app.infra.source_persistence import fetch_and_persist_page
from app.infra.tavily_client import search_tavily

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
        elif job.kind == "sweep_due_jobs":
            await _sweep_due_jobs(db)
        elif job.kind == "sync_countries":
            await _sync_countries(db)
        elif job.kind == "extract_candidate":
            await _extract_candidate(db, job.payload)
        elif job.kind == "prepare_review":
            await _prepare_review(db, job.payload)
        elif job.kind == "harvest_parsebot":
            await _harvest_parsebot(db)
        elif job.kind == "harvest_tavily":
            await _harvest_tavily(db)
        elif job.kind == "refresh_status":
            await refresh_due_statuses(db)
        elif job.kind == "reverify_due":
            await reverify_due_cycles(db)
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


async def execute_due_jobs(db: AsyncSession, *, limit: int = 200) -> tuple[int, int]:
    """Execute every job currently due, returning (completed, failed) counts.

    Shared by the manual run-due admin route and the scheduled sweep_due_jobs
    job kind, so both get the same rollback handling and failure counting
    instead of drifting into two independently maintained copies. By the
    time the scheduled kind runs this, execute_job has already claimed that
    sweep job itself (state -> running), so due_jobs() can never re-select
    it here.
    """
    completed = failed = 0
    for due in await due_jobs(db, limit=limit):
        try:
            await execute_job(db, due.job_id)
            completed += 1
        except Exception:
            failed += 1
            # execute_job's own failure path already tried to commit a
            # recorded failure; if that commit itself failed (a real DB
            # error, not just the job's own logic raising), the session is
            # left needing an explicit rollback, or every job after this one
            # in the batch raises on a poisoned session instead of running.
            await db.rollback()
    return completed, failed


async def _sweep_due_jobs(db: AsyncSession) -> None:
    """The scheduled counterpart to the manual run-due admin route - same
    execute_due_jobs() loop, running automatically instead of requiring
    someone to call the admin endpoint by hand."""
    completed, failed = await execute_due_jobs(db)
    if failed:
        logger.warning(
            "sweep_due_jobs_had_failures", extra={"completed": completed, "failed": failed}
        )


async def _sync_countries(db: AsyncSession) -> None:
    """Refresh the country mirror from Core's public catalogue."""
    settings = get_settings()
    if not settings.core_base_url:
        raise ValueError("CORE_BASE_URL is not configured")
    await sync_countries(db, CoreCatalogueClient(settings.core_base_url))


#: The Router's documented cap on `source_data` once serialized.
AI_ROUTER_SOURCE_DATA_MAX_BYTES = 16 * 1024


async def _extract_candidate(db: AsyncSession, payload: dict) -> None:
    discovery = await db.scalar(
        select(Discovery)
        .where(Discovery.discovery_id == uuid.UUID(payload["discovery_id"]))
        .with_for_update()
    )
    if discovery is None:
        raise LookupError("Discovery not found")
    discovery.extracted_facts = extract_candidate_facts(discovery.raw_title, discovery.raw_excerpt)
    discovery.ai_extracted_facts = await _try_ai_extraction(discovery)
    await db.commit()


async def _try_ai_extraction(discovery: Discovery) -> dict | None:
    """A best-effort AI Router pass, layered on top of the deterministic
    extraction above - never required for extract_candidate to succeed.
    Unconfigured, a non-`completed` outcome, or a transport failure all just
    mean no AI-assisted facts this time, same as if the router did not
    exist; extract_candidate must never fail because of it.
    """
    settings = get_settings()
    if not (
        settings.ai_router_base_url
        and settings.ai_router_private_key_pem
        and settings.ai_router_key_id
    ):
        return None
    excerpt = discovery.raw_excerpt or ""
    if len(excerpt.encode()) > AI_ROUTER_SOURCE_DATA_MAX_BYTES:
        excerpt = excerpt.encode()[:AI_ROUTER_SOURCE_DATA_MAX_BYTES].decode(errors="ignore")
    client = AIRouterClient(
        base_url=settings.ai_router_base_url,
        private_key_pem=settings.ai_router_private_key_pem,
        key_id=settings.ai_router_key_id,
    )
    request = AIRouterRequest(
        task=AITask.scholarship_extraction,
        task_version="v1",
        schema_version=1,
        product_id="scholarship_finder",
        feature_id="extract_candidate",
        correlation_id=str(discovery.discovery_id),
        # Deterministic per discovery, not random per attempt - a retried
        # extract_candidate job must not double-spend the shared budget.
        idempotency_key=f"extract_candidate:{discovery.discovery_id}",
        source_data={"raw_title": discovery.raw_title, "raw_excerpt": excerpt},
    )
    try:
        response = await client.execute(request)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(
            "ai_router_extraction_failed",
            extra={"discovery_id": str(discovery.discovery_id), "error": str(exc)},
        )
        return None
    if response.outcome != AIRouterOutcome.completed:
        return None
    return response.output


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


def _bind_fastweb_major(major: Major) -> Callable[[], list[dict]]:
    """A plain closure, not a lambda with a default-arg workaround: each of
    the 5 Major enum values needs its own zero-arg callable for
    asyncio.to_thread, and a loop-captured lambda without this indirection
    would silently bind every one of them to the loop's final value."""

    def _call() -> list[dict]:
        return fetch_fastweb_by_major(major)

    return _call


async def _harvest_parsebot(db: AsyncSession) -> None:
    """Pull new candidates from every synced Parse.bot marketplace API:
    ScholarshipPortal, PhDScanner, Mastersportal, Opportunity Desk, Fastweb,
    CareerOneStop (.org).

    The kill switch is `Source.active`, not an env flag: deactivating any one
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
    mastersportal = await db.scalar(
        select(Source).where(Source.name == MASTERSPORTAL_SOURCE_NAME, Source.active.is_(True))
    )
    opportunitydesk = await db.scalar(
        select(Source).where(Source.name == OPPORTUNITYDESK_SOURCE_NAME, Source.active.is_(True))
    )
    fastweb = await db.scalar(
        select(Source).where(Source.name == FASTWEB_SOURCE_NAME, Source.active.is_(True))
    )
    careeronestop = await db.scalar(
        select(Source).where(Source.name == CAREERONESTOP_SOURCE_NAME, Source.active.is_(True))
    )
    if (
        scholarshipportal is None
        and phdscanner is None
        and mastersportal is None
        and opportunitydesk is None
        and fastweb is None
        and careeronestop is None
    ):
        logger.info("parsebot_harvest_skipped", extra={"reason": "no_active_source"})
        return

    harvested_at = datetime.now(UTC)
    records: list[FeedRecord] = []
    skipped = 0
    sp_attempts = sp_failures = 0
    phd_attempts = phd_failures = 0
    mp_attempts = mp_failures = 0
    od_attempts = od_failures = 0
    fw_attempts = fw_failures = 0
    cos_attempts = cos_failures = 0

    study_levels: tuple[Literal["master", "phd"], ...] = ("master", "phd")
    if scholarshipportal is not None:
        for destination in sorted(SUPPORTED_DESTINATIONS):
            for study_level in study_levels:
                sp_attempts += 1
                try:
                    raw_items = await asyncio.to_thread(
                        fetch_scholarshipportal, destination, study_level
                    )
                except Exception:
                    sp_failures += 1
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
        _update_harvest_health(
            scholarshipportal, attempts=sp_attempts, failures=sp_failures, now=harvested_at
        )

    if phdscanner is not None:
        for destination in sorted(SUPPORTED_DESTINATIONS):
            phd_attempts += 1
            try:
                raw_items = await asyncio.to_thread(fetch_phdscanner, destination)
            except Exception:
                phd_failures += 1
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
        _update_harvest_health(
            phdscanner, attempts=phd_attempts, failures=phd_failures, now=harvested_at
        )

    if mastersportal is not None:
        for destination in sorted(SUPPORTED_DESTINATIONS):
            mp_attempts += 1
            try:
                raw_items = await asyncio.to_thread(fetch_mastersportal, destination)
            except Exception:
                mp_failures += 1
                logger.warning(
                    "parsebot_fetch_failed",
                    extra={"api": "mastersportal", "destination": destination},
                )
                continue
            for raw in raw_items:
                appended = _map_and_append(
                    records,
                    source_id=mastersportal.source_id,
                    raw=raw,
                    to_record=mastersportal_to_record,
                    harvested_at=harvested_at,
                )
                skipped += not appended
        _update_harvest_health(
            mastersportal, attempts=mp_attempts, failures=mp_failures, now=harvested_at
        )

    if opportunitydesk is not None:
        od_attempts += 1
        try:
            raw_items = await asyncio.to_thread(fetch_opportunitydesk)
        except Exception:
            od_failures += 1
            logger.warning("parsebot_fetch_failed", extra={"api": "opportunitydesk"})
        else:
            for raw in raw_items:
                appended = _map_and_append(
                    records,
                    source_id=opportunitydesk.source_id,
                    raw=raw,
                    to_record=opportunitydesk_to_record,
                    harvested_at=harvested_at,
                )
                skipped += not appended
        _update_harvest_health(
            opportunitydesk, attempts=od_attempts, failures=od_failures, now=harvested_at
        )

    if fastweb is not None:
        fastweb_calls: list[tuple[str, Callable[[], list[dict]]]] = [
            ("featured", fetch_fastweb_featured)
        ]
        for major in Major:
            fastweb_calls.append((major.value, _bind_fastweb_major(major)))
        for label, call in fastweb_calls:
            fw_attempts += 1
            try:
                raw_items = await asyncio.to_thread(call)
            except Exception:
                fw_failures += 1
                logger.warning("parsebot_fetch_failed", extra={"api": "fastweb", "query": label})
                continue
            for raw in raw_items:
                appended = _map_and_append(
                    records,
                    source_id=fastweb.source_id,
                    raw=raw,
                    to_record=fastweb_to_record,
                    harvested_at=harvested_at,
                )
                skipped += not appended
        _update_harvest_health(
            fastweb, attempts=fw_attempts, failures=fw_failures, now=harvested_at
        )

    if careeronestop is not None:
        cos_attempts += 1
        try:
            raw_items = await asyncio.to_thread(fetch_careeronestop)
        except Exception:
            cos_failures += 1
            logger.warning("parsebot_fetch_failed", extra={"api": "careeronestop"})
        else:
            for raw in raw_items:
                appended = _map_and_append(
                    records,
                    source_id=careeronestop.source_id,
                    raw=raw,
                    to_record=careeronestop_to_record,
                    harvested_at=harvested_at,
                )
                skipped += not appended
        _update_harvest_health(
            careeronestop, attempts=cos_attempts, failures=cos_failures, now=harvested_at
        )

    if not records:
        await db.commit()  # persist the harvest-health update even with nothing to import
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


#: Consecutive fully-failed harvest runs before a source is treated as
#: worth a human look, not just a log line - roughly 3 weekly runs, per
#: RECURRING_WEEKLY_KINDS's cadence.
REPEATED_HARVEST_FAILURE_THRESHOLD = 3


def _update_harvest_health(source: Source, *, attempts: int, failures: int, now: datetime) -> None:
    """Record whether every call this run failed for `source` (its
    underlying Parse.bot scraper-as-API may have broken - the target site
    changed, the marketplace listing broke, credentials expired) versus at
    least one succeeding. Attempts == 0 (nothing to fetch this run - a
    source loop can be empty) leaves the counter untouched rather than
    treating "nothing tried" as either a success or a failure.
    """
    if attempts == 0:
        return
    if failures < attempts:
        source.consecutive_harvest_failures = 0
        return
    source.consecutive_harvest_failures += 1
    source.last_harvest_failure_at = now
    if source.consecutive_harvest_failures >= REPEATED_HARVEST_FAILURE_THRESHOLD:
        logger.warning(
            "parsebot_source_repeatedly_failing",
            extra={
                "source_id": str(source.source_id),
                "source_name": source.name,
                "consecutive_harvest_failures": source.consecutive_harvest_failures,
            },
        )


#: Two phrasings per destination cover the graduate/doctoral split without
#: needing a third-party study-level filter the way Parse.bot's APIs have -
#: Tavily has none, so the query text itself carries that intent.
_TAVILY_QUERY_TEMPLATES = (
    "graduate scholarships {country} international students",
    "PhD scholarships {country} international students",
)


async def _harvest_tavily(db: AsyncSession) -> None:
    """Pull candidate URLs from Tavily's web search (Tier C discovery, the
    same evidentiary bucket as harvest_parsebot - see
    docs/candidate-verification-standard.md).

    Deliberately open, not domain-filtered: reviewers already triage every
    Tier-C discovery by hand, the same as ScholarshipRegion/Parse.bot, so
    restricting results to an allowlist here would only risk silently
    dropping a real source before a human ever saw it - the manual spike
    that validated this job found real signal on domains that would fail
    almost any static filter (see docs/scholarship-source-options.md).

    The kill switch is Source.active, matching harvest_parsebot.
    reserve_call gates every search against the shared monthly budget
    (research_budget.py); once refused, the run stops early rather than
    failing the job, keeping whatever it already found this run - the same
    "partial harvest beats losing everything" reasoning harvest_parsebot
    already uses for a single destination's fetch failing.
    """
    settings = get_settings()
    source = await db.scalar(
        select(Source).where(Source.name == TAVILY_SOURCE_NAME, Source.active.is_(True))
    )
    if source is None:
        logger.info("tavily_harvest_skipped", extra={"reason": "no_active_source"})
        return
    if not settings.tavily_api_key:
        logger.info("tavily_harvest_skipped", extra={"reason": "not_configured"})
        return

    harvested_at = datetime.now(UTC)
    records: list[FeedRecord] = []
    skipped = 0
    budget_exhausted = False

    for destination in sorted(SUPPORTED_DESTINATIONS):
        if budget_exhausted:
            break
        country_name = SEED_COUNTRIES.get(destination, destination)
        for template in _TAVILY_QUERY_TEMPLATES:
            if not await reserve_call(db, "tavily", settings.tavily_monthly_search_limit):
                budget_exhausted = True
                break
            query = template.format(country=country_name)
            try:
                raw_items = await search_tavily(query, settings.tavily_api_key)
            except httpx.HTTPError:
                logger.warning(
                    "tavily_fetch_failed", extra={"destination": destination, "query": query}
                )
                continue
            for raw in raw_items:
                appended = _map_and_append(
                    records,
                    source_id=source.source_id,
                    raw=raw,
                    to_record=tavily_result_to_record,
                    harvested_at=harvested_at,
                )
                skipped += not appended

    if not records:
        logger.info(
            "tavily_harvest_empty",
            extra={"skipped": skipped, "budget_exhausted": budget_exhausted},
        )
        return

    outcome = await import_feed_records(db, records)
    logger.info(
        "tavily_harvest_completed",
        extra={
            "skipped": skipped,
            "budget_exhausted": budget_exhausted,
            "imported": outcome.imported,
            "repeated": outcome.repeated,
            "changed": outcome.changed,
            "rejected": outcome.rejected,
        },
    )
