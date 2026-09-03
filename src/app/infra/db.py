from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


@lru_cache
def get_engine():
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,
        connect_args={"timeout": settings.db_connect_timeout_seconds},
    )


async def get_db() -> AsyncGenerator[AsyncSession]:
    session_factory = async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session
