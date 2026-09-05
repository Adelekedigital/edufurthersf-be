"""The Core handoff boundary: ownership, consent and return-URL rules."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

import app.api.routes as routes
from app.domain.return_urls import is_allowed_return_url
from tests.conftest import requires_db

pytestmark = requires_db

SEARCH = {
    "origin_country": "NG",
    "program_level": "masters",
    "field": "health_and_welfare",
    "target_countries": ["CA", "GB"],
}


class _StubCore:
    calls: list[dict[str, Any]] = []

    def __init__(self, *_: Any, **__: Any) -> None:
        pass

    async def create_join_intent(self, payload: dict[str, Any], key: str) -> dict[str, Any]:
        _StubCore.calls.append(payload)
        return {
            "id": "core-intent-1",
            "status": "created",
            "continue_url": "https://core.test/continue?t=token",
            "handoff_token": "handoff-secret",
        }


@pytest.fixture(autouse=True)
def _stub_core(monkeypatch) -> None:
    _StubCore.calls = []
    monkeypatch.setattr(routes, "CoreJoinClient", _StubCore)


def _body(search_id: str, **overrides: Any) -> dict[str, Any]:
    return {
        "search_id": search_id,
        "consent": True,
        "idempotency_key": str(uuid.uuid4()),
        "return_url": "https://app.test/welcome",
        **overrides,
    }


async def test_the_session_that_searched_can_join(client) -> None:
    search_id = (await client.post("/api/v1/search", json=SEARCH)).json()["meta"]["search_id"]
    response = await client.post("/api/v1/join-intents", json=_body(search_id))
    assert response.status_code == 200, response.text
    assert response.json()["handoff_token"] == "handoff-secret"


async def test_another_session_cannot_join_on_a_search_it_did_not_run(client) -> None:
    """Knowing a search_id must not be enough to claim that handoff."""
    from app.main import app

    victim_search = (await client.post("/api/v1/search", json=SEARCH)).json()["meta"]["search_id"]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://finder.test"
    ) as attacker:
        response = await attacker.post("/api/v1/join-intents", json=_body(victim_search))
    assert response.status_code == 404
    assert _StubCore.calls == []


async def test_join_requires_consent(client) -> None:
    search_id = (await client.post("/api/v1/search", json=SEARCH)).json()["meta"]["search_id"]
    response = await client.post("/api/v1/join-intents", json=_body(search_id, consent=False))
    assert response.status_code == 422
    assert _StubCore.calls == []


@pytest.mark.parametrize(
    "return_url",
    [
        "https://app.test.attacker.test/steal",
        "https://app.test@attacker.test/steal",
        "http://app.test/welcome",
        "https://attacker.test/welcome",
    ],
)
async def test_lookalike_return_urls_are_refused(client, return_url: str) -> None:
    search_id = (await client.post("/api/v1/search", json=SEARCH)).json()["meta"]["search_id"]
    response = await client.post(
        "/api/v1/join-intents", json=_body(search_id, return_url=return_url)
    )
    assert response.status_code == 422, f"{return_url} was accepted"
    assert _StubCore.calls == []


def test_return_url_prefix_matching_is_structural() -> None:
    allowed = "https://app.test/"
    assert is_allowed_return_url("https://app.test/welcome", allowed)
    assert is_allowed_return_url("https://APP.test/welcome", allowed)
    assert not is_allowed_return_url("https://app.test.attacker.test/", allowed)
    assert not is_allowed_return_url("https://app.test:8443/welcome", allowed)
    assert not is_allowed_return_url("https://app.test/welcome", "")
    assert is_allowed_return_url("https://app.test/join/step", "https://app.test/join")
    assert not is_allowed_return_url("https://app.test/joinx", "https://app.test/join")
