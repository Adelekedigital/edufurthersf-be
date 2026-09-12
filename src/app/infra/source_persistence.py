import hashlib
import logging
from datetime import UTC, datetime
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domain.models import Source, SourcePage, SourceSnapshot
from app.infra.jina_client import fetch_via_jina
from app.infra.research_budget import reserve_call
from app.infra.source_fetch import FetchedSource, fetch_source

logger = logging.getLogger("app.infra.source_persistence")


async def fetch_and_persist_page(
    db: AsyncSession, page_id: UUID, *, approved_domains_override: list[str] | None = None
) -> UUID:
    """Fetch one approved page and persist an immutable snapshot.

    `approved_domains_override` replaces the owning Source's own
    `approved_domains` for this call only - every SSRF/private-host/redirect
    protection in `fetch_source` still runs unconditionally regardless.
    Exists for `reverify_due` (infra/freshness.py): a reviewer-approved
    `official_cycle_url` is authorized per-record at publish time, not
    pre-vetted per-domain the way the discovery pipeline's own sources are,
    so checking it against a shared domain allowlist built for a different
    purpose would be the wrong check - this makes that divergence explicit
    and localized instead of silently stretching `approved_domains`'s
    meaning or maintaining an ever-growing shared allowlist.
    """
    page = await db.scalar(
        select(SourcePage).where(SourcePage.page_id == page_id).with_for_update()
    )
    if page is None:
        raise LookupError("Source page not found")
    source = await db.scalar(select(Source).where(Source.source_id == page.source_id))
    if source is None or not source.active:
        raise ValueError("Source is inactive or missing")
    domains = (
        approved_domains_override if approved_domains_override is not None
        else source.approved_domains
    )
    fetched, extractor_version = await _fetch_with_jina_fallback(db, page.normalized_url, domains)
    now = datetime.now(UTC)
    content_hash = hashlib.sha256(fetched.content).hexdigest()
    page.last_attempted_at = now
    page.last_successful_fetch_at = (
        now if 200 <= fetched.status_code < 400 else page.last_successful_fetch_at
    )
    page.http_status = fetched.status_code
    page.final_url = fetched.url
    page.normalized_content_hash = content_hash
    snapshot = SourceSnapshot(
        page_id=page.page_id,
        fetched_at=now,
        content_hash=content_hash,
        extractor_version=extractor_version,
        relevant_content={
            "content_type": fetched.content_type,
            "byte_length": len(fetched.content),
        },
    )
    db.add(snapshot)
    await db.commit()
    return snapshot.snapshot_id


async def _fetch_with_jina_fallback(
    db: AsyncSession, url: str, approved_domains: list[str]
) -> tuple[FetchedSource, str]:
    """Try the direct fetcher first; only on a transport failure or a
    blocked/error response, and only if Jina is configured and within
    budget, retry via Jina's Reader as a fallback fetch path.

    Domain-allowlist and SSRF rejections (`ValueError` from `fetch_source`)
    are a policy decision, not a reachability problem - they propagate
    immediately and never trigger the fallback, since Jina fetching from
    its own infrastructure would otherwise bypass that gate entirely.

    Note: `reserve_call` commits `db` internally, which releases the
    calling page row's `with_for_update()` lock early on this (rare,
    failure-only) path - acceptable since every subsequent write still
    lands in the same commit at the end of `fetch_and_persist_page`.
    """
    try:
        fetched = await fetch_source(url, approved_domains)
    except httpx.HTTPError as exc:
        fallback = await _try_jina_fallback(db, url, reason=str(exc))
        if fallback is not None:
            return fallback, "jina-reader-v1"
        raise
    if fetched.status_code >= 400:
        fallback = await _try_jina_fallback(db, url, reason=f"status {fetched.status_code}")
        if fallback is not None:
            return fallback, "jina-reader-v1"
    return fetched, "raw-v1"


async def _try_jina_fallback(
    db: AsyncSession, url: str, *, reason: str
) -> FetchedSource | None:
    """Best-effort only, mirroring `_try_ai_extraction` in infra/worker.py:
    unconfigured, over budget, or a further transport failure all just mean
    no fallback this time, same as if Jina did not exist."""
    settings = get_settings()
    if not settings.jina_api_key:
        return None
    allowed = await reserve_call(db, "jina", settings.jina_monthly_call_limit)
    if not allowed:
        logger.info("jina_fallback_budget_exhausted", extra={"url": url, "reason": reason})
        return None
    try:
        content = await fetch_via_jina(url, settings.jina_api_key)
    except httpx.HTTPError as exc:
        logger.warning(
            "jina_fallback_failed", extra={"url": url, "reason": reason, "error": str(exc)}
        )
        return None
    logger.info("jina_fallback_used", extra={"url": url, "reason": reason})
    return FetchedSource(
        url=url,
        status_code=200,
        content=content.encode(),
        content_type="text/markdown",
    )
