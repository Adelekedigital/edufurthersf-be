"""Creating and listing scholarship providers."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.provider_schemas import ProviderCreateRequest
from app.domain.countries import CountryVocabulary
from app.domain.models import Provider


async def create_provider(
    db: AsyncSession, request: ProviderCreateRequest, *, countries: CountryVocabulary
) -> Provider:
    # Any real country Core publishes, same vocabulary as a searcher's
    # origin - a provider is not limited to Finder's covered destinations.
    country = countries.origin(request.country) if request.country is not None else None
    provider = Provider(
        name=request.name, approved_domains=request.approved_domains, country=country
    )
    db.add(provider)
    await db.flush()
    return provider


async def list_providers(db: AsyncSession) -> list[Provider]:
    return list(await db.scalars(select(Provider).order_by(Provider.name)))
