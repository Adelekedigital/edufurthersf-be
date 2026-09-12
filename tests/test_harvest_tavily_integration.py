"""`_harvest_tavily`: the app-level kill switch, budget gating, and that a
successful run's results actually reach the discovery pipeline."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from sqlalchemy import select

from app.domain.models import Discovery, Source
from app.domain.tavily_harvest import TAVILY_SOURCE_NAME
from app.infra import worker as worker_module
from app.infra.research_budget import reserve_call
from app.infra.worker import _harvest_tavily
from tests.conftest import requires_db

pytestmark = requires_db


@dataclass(frozen=True)
class _FakeSettings:
    tavily_api_key: str | None
    tavily_monthly_search_limit: int = 900


async def _active_source(db) -> Source:
    source = Source(
        name=TAVILY_SOURCE_NAME,
        source_type="web_search",
        authority_grade="C",
        approved_domains=["tavily.com"],
        active=True,
    )
    db.add(source)
    await db.commit()
    return source


def _reject_call(monkeypatch, message: str) -> None:
    async def _unexpected_call(query, api_key, **kwargs):
        raise AssertionError(message)

    monkeypatch.setattr(worker_module, "search_tavily", _unexpected_call)


async def test_no_op_with_no_active_source(db, monkeypatch) -> None:
    monkeypatch.setattr(worker_module, "get_settings", lambda: _FakeSettings("fake-key"))
    _reject_call(monkeypatch, "search_tavily should not have been called")

    await _harvest_tavily(db)


async def test_no_op_without_api_key_configured(db, monkeypatch) -> None:
    await _active_source(db)
    monkeypatch.setattr(worker_module, "get_settings", lambda: _FakeSettings(None))
    _reject_call(monkeypatch, "search_tavily should not have been called")

    await _harvest_tavily(db)


async def test_stops_once_budget_is_exhausted(db, monkeypatch) -> None:
    await _active_source(db)
    monkeypatch.setattr(worker_module, "get_settings", lambda: _FakeSettings("fake-key", 0))
    # limit=0 still lets the very first reserve_call succeed (no existing row
    # to check the WHERE clause against), so pre-exhaust it explicitly.
    assert await reserve_call(db, "tavily", 0) is True
    _reject_call(monkeypatch, "search_tavily should not have been called once refused")

    await _harvest_tavily(db)  # must return cleanly, not raise


async def test_a_single_query_failure_does_not_abort_the_run(db, monkeypatch) -> None:
    await _active_source(db)
    monkeypatch.setattr(worker_module, "get_settings", lambda: _FakeSettings("fake-key"))
    calls: list[str] = []

    async def _flaky(query, api_key, **kwargs):
        calls.append(query)
        if len(calls) == 1:
            raise httpx.ConnectError("boom")
        return [
            {
                "title": f"Real Scholarship {len(calls)}",
                "url": f"https://example.test/award-{len(calls)}",
                "content": "A real scholarship for graduate students.",
            }
        ]

    monkeypatch.setattr(worker_module, "search_tavily", _flaky)

    await _harvest_tavily(db)

    assert len(calls) > 1  # the run kept going past the first failure
    discoveries = list(await db.scalars(select(Discovery)))
    assert len(discoveries) >= 1


async def test_successful_results_reach_the_discovery_pipeline(db, monkeypatch) -> None:
    await _active_source(db)
    monkeypatch.setattr(worker_module, "get_settings", lambda: _FakeSettings("fake-key"))

    async def _fake_search(query, api_key, **kwargs):
        return [
            {
                "title": "Chevening-style Award via Tavily",
                "url": "https://example.test/tavily-award",
                "content": "A real graduate scholarship, discovered via web search.",
            }
        ]

    monkeypatch.setattr(worker_module, "search_tavily", _fake_search)

    await _harvest_tavily(db)

    discovery = await db.scalar(
        select(Discovery).where(Discovery.raw_title == "Chevening-style Award via Tavily")
    )
    assert discovery is not None
    assert discovery.source_page_id is not None
