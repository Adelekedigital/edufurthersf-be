"""`fetch_and_persist_page`'s Jina.ai fallback path.

`fetch_source` and `fetch_via_jina` are monkeypatched at their import sites
in `source_persistence.py`, matching `test_reverify_due_integration.py`'s
convention: this module's own fallback-selection logic is what's under
test, not `fetch_source`'s SSRF boundary or a real Jina call.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass

import httpx
import pytest
from sqlalchemy import select

from app.domain.models import Source, SourcePage, SourceSnapshot
from app.infra import source_persistence as source_persistence_module
from app.infra.research_budget import reserve_call
from app.infra.source_fetch import FetchedSource
from app.infra.source_persistence import fetch_and_persist_page
from tests.conftest import requires_db

pytestmark = requires_db


def test_source_persistence_entrypoint_is_async() -> None:
    assert inspect.iscoroutinefunction(fetch_and_persist_page)


@dataclass(frozen=True)
class _FakeSettings:
    jina_api_key: str | None
    jina_monthly_call_limit: int = 500


async def _page(db) -> SourcePage:
    source = Source(
        name="Example Direct Source",
        source_type="official_direct",
        authority_grade="A",
        approved_domains=["example.test"],
        active=True,
    )
    db.add(source)
    await db.flush()
    page = SourcePage(source_id=source.source_id, normalized_url="https://example.test/award")
    db.add(page)
    await db.commit()
    return page


def _stub_fetch_success(monkeypatch, *, status_code: int = 200, content: bytes = b"hello"):
    async def _fake(url, approved_domains, *, max_bytes=2_000_000):
        return FetchedSource(
            url=url, status_code=status_code, content=content, content_type="text/html"
        )

    monkeypatch.setattr(source_persistence_module, "fetch_source", _fake)


def _stub_fetch_raises(monkeypatch, exc: Exception):
    async def _fake(url, approved_domains, *, max_bytes=2_000_000):
        raise exc

    monkeypatch.setattr(source_persistence_module, "fetch_source", _fake)


def _stub_jina_success(monkeypatch, *, content: str = "# Markdown content"):
    calls: list[str] = []

    async def _fake(url, api_key, *, timeout_seconds=30.0):
        calls.append(url)
        return content

    monkeypatch.setattr(source_persistence_module, "fetch_via_jina", _fake)
    return calls


def _stub_jina_never_called(monkeypatch):
    async def _fake(url, api_key, *, timeout_seconds=30.0):
        raise AssertionError("Jina should not have been called")

    monkeypatch.setattr(source_persistence_module, "fetch_via_jina", _fake)


def _configure_jina(monkeypatch, *, api_key: str | None = "fake-jina-key", limit: int = 500):
    monkeypatch.setattr(
        source_persistence_module, "get_settings", lambda: _FakeSettings(api_key, limit)
    )


async def test_successful_direct_fetch_never_calls_jina(db, monkeypatch) -> None:
    page = await _page(db)
    _stub_fetch_success(monkeypatch, status_code=200)
    _stub_jina_never_called(monkeypatch)
    _configure_jina(monkeypatch)

    await fetch_and_persist_page(db, page.page_id)

    await db.refresh(page)
    assert page.http_status == 200


async def test_transport_failure_falls_back_to_jina_when_configured(db, monkeypatch) -> None:
    page = await _page(db)
    _stub_fetch_raises(monkeypatch, httpx.ConnectError("boom"))
    jina_calls = _stub_jina_success(monkeypatch, content="# Real content")
    _configure_jina(monkeypatch)

    snapshot_id = await fetch_and_persist_page(db, page.page_id)

    assert jina_calls == ["https://example.test/award"]
    await db.refresh(page)
    assert page.http_status == 200
    snapshot = await db.scalar(
        select(SourceSnapshot).where(SourceSnapshot.snapshot_id == snapshot_id)
    )
    assert snapshot.extractor_version == "jina-reader-v1"
    assert snapshot.relevant_content["content_type"] == "text/markdown"


async def test_blocked_status_falls_back_to_jina(db, monkeypatch) -> None:
    page = await _page(db)
    _stub_fetch_success(monkeypatch, status_code=403, content=b"blocked")
    _stub_jina_success(monkeypatch, content="# Fetched via Jina instead")
    _configure_jina(monkeypatch)

    snapshot_id = await fetch_and_persist_page(db, page.page_id)
    snapshot = await db.scalar(
        select(SourceSnapshot).where(SourceSnapshot.snapshot_id == snapshot_id)
    )
    assert snapshot.extractor_version == "jina-reader-v1"


async def test_transport_failure_without_jina_configured_reraises(db, monkeypatch) -> None:
    page = await _page(db)
    _stub_fetch_raises(monkeypatch, httpx.ConnectError("boom"))
    _stub_jina_never_called(monkeypatch)
    _configure_jina(monkeypatch, api_key=None)

    with pytest.raises(httpx.ConnectError):
        await fetch_and_persist_page(db, page.page_id)


async def test_jina_never_called_when_budget_exhausted(db, monkeypatch) -> None:
    page = await _page(db)
    _stub_fetch_raises(monkeypatch, httpx.ConnectError("boom"))
    _stub_jina_never_called(monkeypatch)
    _configure_jina(monkeypatch, limit=1)
    assert await reserve_call(db, "jina", 1) is True  # exhausts the limit=1 budget

    with pytest.raises(httpx.ConnectError):
        await fetch_and_persist_page(db, page.page_id)


async def test_domain_policy_rejection_never_triggers_jina_fallback(db, monkeypatch) -> None:
    page = await _page(db)
    _stub_fetch_raises(monkeypatch, ValueError("Source URL domain is not approved"))
    _stub_jina_never_called(monkeypatch)
    _configure_jina(monkeypatch)

    with pytest.raises(ValueError, match="Source URL domain is not approved"):
        await fetch_and_persist_page(db, page.page_id)


async def test_jina_transport_failure_reraises_the_original_error(db, monkeypatch) -> None:
    page = await _page(db)
    _stub_fetch_raises(monkeypatch, httpx.ConnectError("original failure"))
    _configure_jina(monkeypatch)

    async def _jina_fails(url, api_key, *, timeout_seconds=30.0):
        raise httpx.ReadTimeout("jina timed out")

    monkeypatch.setattr(source_persistence_module, "fetch_via_jina", _jina_fails)

    with pytest.raises(httpx.ConnectError, match="original failure"):
        await fetch_and_persist_page(db, page.page_id)
