"""`GET /api/v1/search/{search_id}`: replay a stored search without
re-running matching."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.routes import search_limiter, search_replay_limiter
from app.domain.models import PublicStatus, RecordState, Scholarship, Search
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
    assert body["filters"]["program_levels"] == SEARCH["program_levels"]
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
    response = await client.get("/api/v1/search/01960000-0000-7000-8000-000000000000")
    assert response.status_code == 404


async def test_a_different_sessions_search_is_a_404(db, client) -> None:
    """The attacker has their own *valid* session (not just a missing
    cookie) - this is what actually exercises the session_id-scoping
    predicate, not just the "no session at all" path already covered by
    test_no_cookie_at_all_is_a_404_and_never_mints_a_session."""
    await _publish(db, slug="a", facts=CONFIRMED_FACTS, status=PublicStatus.open_verified)
    victim_search_id = (await client.post("/api/v1/search", json=SEARCH)).json()["meta"][
        "search_id"
    ]

    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://finder.test"
    ) as attacker:
        await attacker.post("/api/v1/search", json=SEARCH)  # mints the attacker's own session
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


async def test_replay_response_is_never_cached(db, client) -> None:
    await _publish(db, slug="a", facts=CONFIRMED_FACTS, status=PublicStatus.open_verified)
    search_id = (await client.post("/api/v1/search", json=SEARCH)).json()["meta"]["search_id"]

    response = await client.get(f"/api/v1/search/{search_id}")
    assert response.headers["cache-control"] == "private, no-store"


async def test_a_malformed_stored_snapshot_is_a_404_not_a_500(db, client) -> None:
    """result_snapshot is only ever written by build_result_snapshot, but
    nothing at the database level guarantees that - a row shaped for an
    older/narrower ALLOWED_RESULT_KEYS must degrade to 404, the same way a
    missing search does, not crash the request."""
    await _publish(db, slug="a", facts=CONFIRMED_FACTS, status=PublicStatus.open_verified)
    search_id = (await client.post("/api/v1/search", json=SEARCH)).json()["meta"]["search_id"]

    stored = await db.scalar(select(Search))
    snapshot = dict(stored.result_snapshot)
    # Strip a required SearchResult field from every result row.
    snapshot["data"] = [
        {key: value for key, value in item.items() if key != "award_type"}
        for item in snapshot["data"]
    ]
    stored.result_snapshot = snapshot
    await db.commit()

    response = await client.get(f"/api/v1/search/{search_id}")
    assert response.status_code == 404


async def test_a_cursor_redeemed_with_a_different_limit_is_rejected(db, client) -> None:
    """Changing `limit` between the original search and a cursor-based page
    request must not be allowed to silently collide page_number back to 1
    and overwrite the real first page - see encode_cursor's own docstring."""
    for index in range(3):
        await _publish(
            db, slug=f"s{index}", facts=CONFIRMED_FACTS, status=PublicStatus.open_verified
        )
    first_page = (await client.post("/api/v1/search", json={**SEARCH, "limit": 1})).json()
    search_id = first_page["meta"]["search_id"]
    cursor = first_page["next_cursor"]
    assert cursor  # 3 matches, limit 1 -> a next page exists

    response = await client.post("/api/v1/search", json={**SEARCH, "limit": 2, "cursor": cursor})
    assert response.status_code == 400

    # The real page-one row for this specific search must be untouched by
    # the rejected attempt - still limit 1's data, not overwritten by an
    # (attempted, rejected) limit-2 redemption computing back to page_number=1.
    page_one = await db.scalar(select(Search).where(Search.search_id == search_id))
    assert page_one.requested_limit == 1
    assert page_one.returned_count == 1


async def test_a_withdrawn_scholarship_is_omitted_from_the_replay(db, client) -> None:
    await _publish(db, slug="a", facts=CONFIRMED_FACTS, status=PublicStatus.open_verified)
    original = (await client.post("/api/v1/search", json=SEARCH)).json()
    search_id = original["meta"]["search_id"]
    assert len(original["data"]) == 1

    scholarship = await db.scalar(select(Scholarship))
    scholarship.lifecycle_state = RecordState.withdrawn
    await db.commit()

    response = await client.get(f"/api/v1/search/{search_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data"] == []
    # The historical record of what the search actually found is untouched.
    assert body["meta"]["confirmed_counts"] == original["meta"]["confirmed_counts"]
