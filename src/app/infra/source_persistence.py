import hashlib
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Source, SourcePage, SourceSnapshot
from app.infra.source_fetch import fetch_source


async def fetch_and_persist_page(db: AsyncSession, page_id: UUID) -> UUID:
    """Fetch one approved page and persist an immutable snapshot."""
    page = await db.scalar(
        select(SourcePage).where(SourcePage.page_id == page_id).with_for_update()
    )
    if page is None:
        raise LookupError("Source page not found")
    source = await db.scalar(select(Source).where(Source.source_id == page.source_id))
    if source is None or not source.active:
        raise ValueError("Source is inactive or missing")
    fetched = await fetch_source(page.normalized_url, source.approved_domains)
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
