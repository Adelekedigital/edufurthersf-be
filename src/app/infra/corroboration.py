"""Load the other discoveries sharing a discovery's identity key and score
whether they corroborate it - the DB-backed half of `domain/corroboration.py`.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.corroboration import CorroborationResult, SiblingFact, evaluate_corroboration
from app.domain.models import Discovery, Source, SourcePage


async def load_siblings(db: AsyncSession, discovery: Discovery) -> list[SiblingFact]:
    """Every other discovery sharing this one's `normalized_identity_key`,
    regardless of which one `link_discovery` picked as "the original" - the
    match is a star (one original, N duplicates all pointing at it directly),
    so this is the only way to see every source that reported the identity.
    """
    if not discovery.normalized_identity_key:
        return []
    rows = await db.execute(
        select(Discovery.discovery_id, Source.source_id, Discovery.extracted_facts)
        .join(SourcePage, SourcePage.page_id == Discovery.source_page_id)
        .join(Source, Source.source_id == SourcePage.source_id)
        .where(
            Discovery.normalized_identity_key == discovery.normalized_identity_key,
            Discovery.discovery_id != discovery.discovery_id,
        )
    )
    return [(row[0], row[1], row[2]) for row in rows.all()]


async def gather_corroboration(db: AsyncSession, discovery: Discovery) -> CorroborationResult:
    own_source_id = await db.scalar(
        select(Source.source_id)
        .join(SourcePage, SourcePage.source_id == Source.source_id)
        .where(SourcePage.page_id == discovery.source_page_id)
    )
    if own_source_id is None:
        raise LookupError("Discovery's source could not be resolved")
    siblings = await load_siblings(db, discovery)
    return evaluate_corroboration(
        own_source_id=own_source_id, own_facts=discovery.extracted_facts, siblings=siblings
    )
