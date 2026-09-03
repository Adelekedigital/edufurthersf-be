from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ingestion_schemas import FeedRecord
from app.domain.ingestion import prepare_candidate
from app.domain.models import Discovery, ProcessingJob, Source, SourcePage
from app.domain.normalization import normalize_discovery


async def import_feed_records(db: AsyncSession, records: list[FeedRecord]) -> tuple[int, int, int]:
    accepted = duplicates = rejected = 0
    for record in records:
        try:
            candidate = prepare_candidate(str(record.url), record.title, record.excerpt)
        except ValueError:
            rejected += 1
            continue
        source = await db.scalar(
            select(Source).where(Source.source_id == record.source_id, Source.active.is_(True))
        )
        if source is None:
            rejected += 1
            continue
        page = await db.scalar(
            select(SourcePage).where(
                SourcePage.source_id == source.source_id,
                SourcePage.normalized_url == candidate.normalized_url,
            )
        )
        if page is None:
            page = SourcePage(source_id=source.source_id, normalized_url=candidate.normalized_url)
            db.add(page)
            await db.flush()
        existing = await db.scalar(
            select(Discovery).where(
                Discovery.source_page_id == page.page_id,
                Discovery.content_hash == candidate.content_hash,
            )
        )
        if existing is not None:
            duplicates += 1
            continue
        normalized = normalize_discovery(candidate.title)
        discovery = Discovery(
            source_page_id=page.page_id,
            content_hash=candidate.content_hash,
            raw_title=candidate.title,
            raw_excerpt=candidate.excerpt,
            normalized_identity_key=normalized.identity_key,
            processing_state="normalized",
        )
        db.add(discovery)
        await db.flush()
        db.add(
            ProcessingJob(
                kind="normalize_discovery",
                dedupe_key=f"normalize:{discovery.discovery_id}:{normalized.identity_key}",
                payload={"discovery_id": str(discovery.discovery_id)},
            )
        )
        accepted += 1
    await db.commit()
    return accepted, duplicates, rejected
