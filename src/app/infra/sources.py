"""Creating and listing approved crawl sources."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.source_schemas import SourceCreateRequest
from app.domain.models import Source


async def create_source(db: AsyncSession, request: SourceCreateRequest) -> Source:
    source = Source(
        name=request.name,
        source_type=request.source_type,
        authority_grade=request.authority_grade,
        approved_domains=request.approved_domains,
        active=request.active,
    )
    db.add(source)
    await db.flush()
    return source


async def list_sources(db: AsyncSession) -> list[Source]:
    return list(await db.scalars(select(Source).order_by(Source.name)))
