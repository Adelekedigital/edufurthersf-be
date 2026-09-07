"""Creating and listing scholarship providers."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.provider_schemas import ProviderCreateRequest
from app.domain.models import Provider
from app.infra.countries import load_vocabulary


async def create_provider(db: AsyncSession, request: ProviderCreateRequest) -> Provider:
    country = None
    if request.country is not None:
        # Any real country Core publishes, same vocabulary as a searcher's
        # origin - a provider is not limited to Finder's covered destinations.
        vocabulary = await load_vocabulary(db)
        country = vocabulary.origin(request.country)
    provider = Provider(
        name=request.name, approved_domains=request.approved_domains, country=country
    )
    db.add(provider)
    await db.flush()
    return provider


async def list_providers(db: AsyncSession) -> list[Provider]:
    return list(await db.scalars(select(Provider).order_by(Provider.name)))
