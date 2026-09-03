"""Integration-test fixtures backed by a real PostgreSQL database.

The suite previously ran entirely against pure functions, so defects that only
appear against real Postgres — a column type the ORM and migration disagreed
on, a transaction that was never committed — reached deployment unnoticed.
Set TEST_DATABASE_URL to point at a disposable database.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@127.0.0.1:55433/scholarship_finder_test",
)

requires_db = pytest.mark.skipif(
    os.environ.get("SKIP_DB_TESTS") == "1",
    reason="SKIP_DB_TESTS=1; a pass with database tests skipped is not a full pass",
)


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def database_url() -> str:
    return TEST_DATABASE_URL


@pytest.fixture(autouse=True, scope="session")
def _configure_environment(database_url: str) -> None:
    os.environ["DATABASE_URL"] = database_url
    os.environ.setdefault("CORE_JOIN_INTENT_URL", "https://core.test/api/v1/internal/join-intents")
    os.environ.setdefault("CORE_SERVICE_TOKEN", "core-service-token")
    os.environ.setdefault("CORE_ALLOWED_RETURN_URL_PREFIX", "https://app.test/")
    os.environ.setdefault("INTERNAL_SERVICE_TOKEN", "internal-service-token")
    from app.core.config import get_settings

    get_settings.cache_clear()


@pytest.fixture
async def engine(database_url: str):
    engine = create_async_engine(database_url, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db(engine) -> AsyncGenerator[AsyncSession]:
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session


@pytest.fixture(autouse=True)
async def _clean_tables(engine) -> AsyncGenerator[None]:
    """Truncate between tests so ordering cannot make one test depend on another."""
    from sqlalchemy import text

    yield
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE searches, anonymous_sessions, join_requests, scholarship_cycles, "
                "scholarship_revisions, scholarships, providers, processing_jobs, "
                "review_tasks, discoveries, source_snapshots, source_pages, sources, "
                "outbox_events, consumer_receipts, audit_log, verifications, countries, "
                "verification_evidence RESTART IDENTITY CASCADE"
            )
        )


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://finder.test"
    ) as http_client:
        yield http_client
