"""External research provider (Tavily, Jina.ai) monthly call budgets - the
enforcement nothing in this codebase had before (Parse.bot just stays
conservative by convention, RESULTS_PER_CALL, never actually enforced)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app.domain.models import ResearchProviderUsage
from app.infra.research_budget import current_period_key, reserve_call
from tests.conftest import requires_db

pytestmark = requires_db


def test_current_period_key_is_the_calendar_month() -> None:
    assert current_period_key(datetime(2026, 9, 15)) == "2026-09"
    assert current_period_key(datetime(2026, 1, 1)) == "2026-01"


async def test_reserve_call_allows_up_to_the_limit_then_refuses(db) -> None:
    for _ in range(3):
        assert await reserve_call(db, "tavily", 3, now=datetime(2026, 9, 1)) is True
    assert await reserve_call(db, "tavily", 3, now=datetime(2026, 9, 1)) is False


async def test_reserve_call_does_not_increment_once_refused(db) -> None:
    assert await reserve_call(db, "jina", 1, now=datetime(2026, 9, 1)) is True
    for _ in range(3):
        assert await reserve_call(db, "jina", 1, now=datetime(2026, 9, 1)) is False

    row = await db.scalar(
        select(ResearchProviderUsage).where(
            ResearchProviderUsage.provider == "jina",
            ResearchProviderUsage.period_key == "2026-09",
        )
    )
    assert row.calls_used == 1


async def test_reserve_call_resets_on_a_new_calendar_month(db) -> None:
    assert await reserve_call(db, "tavily", 1, now=datetime(2026, 9, 30)) is True
    assert await reserve_call(db, "tavily", 1, now=datetime(2026, 9, 30)) is False
    # A new calendar month is a fresh budget, not a continuation.
    assert await reserve_call(db, "tavily", 1, now=datetime(2026, 10, 1)) is True


async def test_reserve_call_budgets_are_scoped_per_provider(db) -> None:
    assert await reserve_call(db, "tavily", 1, now=datetime(2026, 9, 1)) is True
    assert await reserve_call(db, "tavily", 1, now=datetime(2026, 9, 1)) is False
    # A different provider's budget is untouched by tavily's exhaustion.
    assert await reserve_call(db, "jina", 1, now=datetime(2026, 9, 1)) is True
