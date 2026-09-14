"""Creating and listing approved crawl sources."""

from __future__ import annotations

import uuid

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


async def update_source_domains(
    db: AsyncSession, source_id: uuid.UUID, approved_domains: list[str]
) -> Source:
    """Replace a Source's approved-domain allowlist.

    Real-page verification (`infra/source_verification.py`) validates a
    discovery's actual underlying URL against this list - a Source whose
    upstream API returns pages on a different domain than originally
    assumed (confirmed for ScholarshipPortal, whose Parse.bot API actually
    returns mastersportal.com URLs) needs this corrected here, not worked
    around downstream.
    """
    source = await db.scalar(select(Source).where(Source.source_id == source_id))
    if source is None:
        raise LookupError("Source not found")
    source.approved_domains = approved_domains
    await db.commit()
    await db.refresh(source)
    return source


async def deactivate_source(db: AsyncSession, source_id: uuid.UUID) -> Source:
    """Stop a source from being treated as an approved crawl input.

    Never a hard delete: a source already linked to discoveries or source
    pages must keep existing, just stop being usable for anything new - a
    delete would either cascade into real ingestion history or fail on the
    foreign key, neither of which is what "clean this up" means here.
    """
    source = await db.scalar(select(Source).where(Source.source_id == source_id))
    if source is None:
        raise LookupError("Source not found")
    source.active = False
    await db.commit()
    await db.refresh(source)
    return source
