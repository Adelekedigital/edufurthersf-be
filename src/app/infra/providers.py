"""Creating and listing scholarship providers."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.provider_schemas import ProviderCreateRequest
from app.domain.models import Provider


async def create_provider(db: AsyncSession, request: ProviderCreateRequest) -> Provider:
    provider = Provider(name=request.name, approved_domains=request.approved_domains)
    db.add(provider)
    await db.flush()
    return provider


async def list_providers(db: AsyncSession) -> list[Provider]:
    return list(await db.scalars(select(Provider).order_by(Provider.name)))
