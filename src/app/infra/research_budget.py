"""Per-provider monthly call budgets for external research APIs (Tavily,
Jina.ai) used to widen scholarship discovery/verification beyond Parse.bot.
Nothing tracked usage against any external quota before this."""

from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import ResearchProviderUsage


def current_period_key(now: datetime | None = None) -> str:
    """Calendar-month key, matching the cadence a monthly credit grant resets on."""
    return (now or datetime.now(UTC)).strftime("%Y-%m")


async def reserve_call(
    db: AsyncSession, provider: str, limit: int, *, now: datetime | None = None
) -> bool:
    """Reserve one call against `provider`'s current-period budget.

    A single atomic INSERT ... ON CONFLICT DO UPDATE ... WHERE, matching this
    codebase's own enqueue_job idiom (insert + on_conflict + returning): the
    increment and the limit check happen as one statement, so two concurrent
    callers can never both read "one call under the limit" and both proceed.
    Call this immediately before the real external HTTP call, and skip/stop
    on `False` rather than making the call and accounting for it after.
    """
    period_key = current_period_key(now)
    statement = (
        insert(ResearchProviderUsage)
        .values(provider=provider, period_key=period_key, calls_used=1)
        .on_conflict_do_update(
            index_elements=["provider", "period_key"],
            set_={"calls_used": ResearchProviderUsage.calls_used + 1},
            where=ResearchProviderUsage.calls_used < limit,
        )
        .returning(ResearchProviderUsage.calls_used)
    )
    result = await db.execute(statement)
    await db.commit()
    return result.first() is not None
