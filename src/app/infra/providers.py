"""Creating and listing scholarship providers."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.provider_schemas import ProviderCreateRequest
from app.domain.countries import CountryVocabulary
from app.domain.models import Provider


async def create_provider(
    db: AsyncSession, request: ProviderCreateRequest, *, countries: CountryVocabulary | None
) -> Provider:
    # Any real country Core publishes, same vocabulary as a searcher's
    # origin - a provider is not limited to Finder's covered destinations.
    # `countries` is only None when request.country is also None - the
    # route skips the vocabulary fetch entirely rather than paying a full
    # table load on every provider creation just in case one's needed.
    country = None
    if request.country is not None and countries is not None:
        country = countries.origin(request.country)
    provider = Provider(
        name=request.name, approved_domains=request.approved_domains, country=country
    )
    db.add(provider)
    await db.flush()
    return provider


async def list_providers(db: AsyncSession) -> list[Provider]:
    return list(await db.scalars(select(Provider).order_by(Provider.name)))
