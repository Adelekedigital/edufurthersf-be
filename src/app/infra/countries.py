"""Keeping the local country mirror current, and reading it."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_uuid7
from app.domain.countries import SEED_COUNTRIES, SUPPORTED_DESTINATIONS, CountryVocabulary
from app.domain.models import Country
from app.infra.core_catalogue import CatalogueEntry, CoreCatalogueClient


async def sync_countries(db: AsyncSession, client: CoreCatalogueClient) -> dict[str, int]:
    """Refresh the mirror from Core's catalogue.

    Upsert only. A country that disappears from Core is left in place rather
    than deleted: rows elsewhere refer to it by code, and a truncated or
    partially fetched response must not silently empty the vocabulary that
    search validates against.

    `is_supported_destination` is Finder's coverage decision, not Core's, so
    a sync only ever turns it on, never off - an already-supported
    destination must never be silently withdrawn just because a later
    `SUPPORTED_DESTINATIONS` doesn't happen to list it that call. But a
    row that already existed before its code was added to
    `SUPPORTED_DESTINATIONS` (the common case - Core's catalogue lists a
    country long before Finder decides to support it as a destination)
    must still pick up that support on the next sync, not stay stuck at
    whatever was true on first insert forever.
    """
    entries = await client.list_catalogue("countries")
    if not entries:
        raise ValueError("Core returned no countries; refusing to treat that as a valid sync")
    now = datetime.now(UTC)
    for entry in entries:
        await _upsert(db, entry, now=now)
    await db.commit()
    return {"received": len(entries)}


async def _upsert(db: AsyncSession, entry: CatalogueEntry, *, now: datetime) -> None:
    code = entry.code.strip().upper()
    statement = insert(Country).values(
        country_id=new_uuid7(),
        code=code,
        display_name=entry.display_name,
        core_id=entry.core_id,
        is_supported_destination=code in SUPPORTED_DESTINATIONS,
        synced_at=now,
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=["code"],
            set_={
                "display_name": statement.excluded.display_name,
                "core_id": statement.excluded.core_id,
                "synced_at": statement.excluded.synced_at,
                "is_supported_destination": (
                    Country.is_supported_destination | statement.excluded.is_supported_destination
                ),
            },
        )
    )


async def load_vocabulary(db: AsyncSession) -> CountryVocabulary:
    """Read the mirror, falling back to the built-in seed when it is empty.

    A database with no mirror yet — a fresh environment, or one where the sync
    has not run — must still answer searches, so the seed stands in rather than
    leaving every country invalid.
    """
    rows = list(await db.scalars(select(Country).order_by(Country.display_name)))
    if not rows:
        return CountryVocabulary(names=dict(SEED_COUNTRIES), destinations=SUPPORTED_DESTINATIONS)
    return CountryVocabulary(
        names={row.code: row.display_name for row in rows},
        destinations=frozenset(row.code for row in rows if row.is_supported_destination)
        or SUPPORTED_DESTINATIONS,
    )
