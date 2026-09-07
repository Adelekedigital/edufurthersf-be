"""`GET /api/v1/search/{search_id}`: replay a stored search without
re-running matching."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.routes import search_limiter, search_replay_limiter
from app.domain.models import PublicStatus, Search
from tests.conftest import requires_db
from tests.test_search_integration import CONFIRMED_FACTS, POSSIBLE_FACTS, SEARCH, _publish

pytestmark = requires_db


@pytest.fixture(autouse=True)
def _reset_search_limiters():
    """Both limiters are process-global singletons (routes.py module scope),
    so a dense run of search-heavy test files back to back within the same
    60-second sliding window can otherwise trip the real per-IP cap - this
    file alone makes a couple dozen POST/GET /search calls. Matches the
    established match_explanation_limiter reset pattern."""
    search_limiter._requests.clear()
    search_replay_limiter._requests.clear()
    yield
    search_limiter._requests.clear()
    search_replay_limiter._requests.clear()


async def test_replay_returns_the_stored_page_and_filters(db, client) -> None:
    await _publish(db, slug="a", facts=CONFIRMED_FACTS, status=PublicStatus.open_verified)
    original = (await client.post("/api/v1/search", json=SEARCH)).json()
    search_id = original["meta"]["search_id"]

    response = await client.get(f"/api/v1/search/{search_id}")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["data"] == original["data"]
    assert body["meta"]["search_id"] == search_id
    assert body["meta"]["response_id"] == original["meta"]["response_id"]
    assert body["meta"]["evaluated_at"] == original["meta"]["evaluated_at"]
    assert body["meta"]["match_policy_version"] == original["meta"]["match_policy_version"]
    assert body["meta"]["taxonomy_version"] == original["meta"]["taxonomy_version"]
    assert body["meta"]["confirmed_counts"] == original["meta"]["confirmed_counts"]
    assert body["meta"]["possible_match_count"] == original["meta"]["possible_match_count"]
    assert body["meta"]["warnings"] == original["meta"]["warnings"]
    assert body["next_cursor"] is None
    # Exactly what the modal-explanation endpoint's MatchProfileRequest needs.
    assert body["filters"]["origin_country"] == SEARCH["origin_country"]
    assert body["filters"]["program_level"] == SEARCH["program_level"]
    assert body["filters"]["field"] == SEARCH["field"]


async def test_replay_reports_real_aggregate_counts_not_just_this_page(db, client) -> None:
    await _publish(db, slug="confirmed", facts=CONFIRMED_FACTS, status=PublicStatus.open_verified)
    await _publish(db, slug="possible", facts=POSSIBLE_FACTS, status=PublicStatus.open_verified)
    original = (await client.post("/api/v1/search", json=SEARCH)).json()
    search_id = original["meta"]["search_id"]

    body = (await client.get(f"/api/v1/search/{search_id}")).json()
    assert body["meta"]["possible_match_count"] == 1
    assert sum(body["meta"]["confirmed_counts"].values()) == 1


async def test_unknown_search_id_is_a_404(client) -> None:
    response = await client.get(
        "/api/v1/search/01960000-0000-7000-8000-000000000000"
    )
    assert response.status_code == 404


async def test_a_different_sessions_search_is_a_404(db, client) -> None:
    await _publish(db, slug="a", facts=CONFIRMED_FACTS, status=PublicStatus.open_verified)
    victim_search_id = (await client.post("/api/v1/search", json=SEARCH)).json()["meta"][
        "search_id"
    ]

    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://finder.test"
    ) as attacker:
        response = await attacker.get(f"/api/v1/search/{victim_search_id}")
    assert response.status_code == 404


async def test_no_cookie_at_all_is_a_404_and_never_mints_a_session(db, client) -> None:
    await _publish(db, slug="a", facts=CONFIRMED_FACTS, status=PublicStatus.open_verified)
    search_id = (await client.post("/api/v1/search", json=SEARCH)).json()["meta"]["search_id"]

    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://finder.test"
    ) as no_cookie_client:
        response = await no_cookie_client.get(f"/api/v1/search/{search_id}")
    assert response.status_code == 404
    assert "finder_session" not in response.cookies


async def test_an_expired_search_is_a_404(db, client) -> None:
    await _publish(db, slug="a", facts=CONFIRMED_FACTS, status=PublicStatus.open_verified)
    original = (await client.post("/api/v1/search", json=SEARCH)).json()
    search_id = original["meta"]["search_id"]

    stored = await db.scalar(select(Search))
    stored.expires_at = datetime.now(UTC) - timedelta(days=1)
    await db.commit()

    response = await client.get(f"/api/v1/search/{search_id}")
    assert response.status_code == 404


async def test_replayed_next_cursor_actually_fetches_the_next_page(db, client) -> None:
    for index in range(3):
        await _publish(
            db, slug=f"s{index}", facts=CONFIRMED_FACTS, status=PublicStatus.open_verified
        )
    original = (await client.post("/api/v1/search", json={**SEARCH, "limit": 2})).json()
    search_id = original["meta"]["search_id"]
    assert original["next_cursor"]

    replayed = (await client.get(f"/api/v1/search/{search_id}")).json()
    assert replayed["next_cursor"]

    second_page = await client.post(
        "/api/v1/search", json={**SEARCH, "limit": 2, "cursor": replayed["next_cursor"]}
    )
    assert second_page.status_code == 200, second_page.text
    body = second_page.json()
    assert body["meta"]["search_id"] == search_id
    assert len(body["data"]) == 1  # 3 matches, limit 2 -> page 2 has the remainder


async def test_a_pre_migration_row_replays_with_null_counts(db, client) -> None:
    """A search stored before confirmed_counts/possible_match_count started
    being persisted must still replay cleanly - not crash, not fabricate a
    number for what genuinely isn't known."""
    await _publish(db, slug="a", facts=CONFIRMED_FACTS, status=PublicStatus.open_verified)
    original = (await client.post("/api/v1/search", json=SEARCH)).json()
    search_id = original["meta"]["search_id"]

    stored = await db.scalar(select(Search))
    snapshot = dict(stored.result_snapshot)
    meta = dict(snapshot["meta"])
    meta.pop("confirmed_counts", None)
    meta.pop("possible_match_count", None)
    snapshot["meta"] = meta
    stored.result_snapshot = snapshot
    await db.commit()

    response = await client.get(f"/api/v1/search/{search_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["meta"]["confirmed_counts"] is None
    assert body["meta"]["possible_match_count"] is None
