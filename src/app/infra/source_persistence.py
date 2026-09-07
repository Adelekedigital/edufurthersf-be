import hashlib
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Source, SourcePage, SourceSnapshot
from app.infra.source_fetch import fetch_source


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
    fetched = await fetch_source(page.normalized_url, domains)
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
        extractor_version="raw-v1",
        relevant_content={
            "content_type": fetched.content_type,
            "byte_length": len(fetched.content),
        },
    )
    db.add(snapshot)
    await db.commit()
    return snapshot.snapshot_id
