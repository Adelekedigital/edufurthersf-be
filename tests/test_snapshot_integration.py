"""Search history: what was returned, grouped by logical search."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.domain.models import OutboxEvent, PublicStatus, Search
from app.domain.snapshots import ALLOWED_RESULT_KEYS, build_result_snapshot
from tests.conftest import requires_db
from tests.test_search_integration import CONFIRMED_FACTS, SEARCH, _publish

pytestmark = requires_db


async def test_the_returned_page_is_stored(db, client) -> None:
    await _publish(db, slug="a", facts=CONFIRMED_FACTS, status=PublicStatus.open_verified)
    body = (await client.post("/api/v1/search", json=SEARCH)).json()

    stored = await db.scalar(select(Search))
    snapshot = stored.result_snapshot
    assert [row["name"] for row in snapshot["data"]] == [item["name"] for item in body["data"]]
    assert snapshot["data"][0]["status"] == body["data"][0]["status"]
    assert snapshot["meta"]["total_match_count"] == 1
    assert snapshot["pagination"] == {
        "page_number": 1,
        "requested_limit": 20,
        "has_next_page": False,
    }
    assert stored.returned_count == 1
    assert stored.expires_at is not None


async def test_a_zero_result_search_is_recorded_as_a_success(db, client) -> None:
    """An empty result is a real answer; it must not look like a failed request."""
    body = (await client.post("/api/v1/search", json=SEARCH)).json()
    assert body["data"] == []
    stored = await db.scalar(select(Search))
    assert stored.result_snapshot["data"] == []
    assert stored.returned_count == 0
    assert stored.total_match_count == 0


async def test_paging_stays_one_logical_search_with_separate_rows(db, client) -> None:
    for index in range(3):
        await _publish(
            db, slug=f"s{index}", facts=CONFIRMED_FACTS, status=PublicStatus.open_verified
        )
    first = (await client.post("/api/v1/search", json={**SEARCH, "limit": 2})).json()
    assert first["next_cursor"]

    second = (
        await client.post(
            "/api/v1/search", json={**SEARCH, "limit": 2, "cursor": first["next_cursor"]}
        )
    ).json()

    assert second["meta"]["search_id"] == first["meta"]["search_id"], "paging is one search"
    assert second["meta"]["response_id"] != first["meta"]["response_id"]
    rows = list(await db.scalars(select(Search).order_by(Search.page_number)))
    assert [row.page_number for row in rows] == [1, 2]
    assert rows[0].result_snapshot["data"] != rows[1].result_snapshot["data"]


async def test_only_the_first_page_emits_a_completed_search_event(db, client) -> None:
    for index in range(3):
        await _publish(
            db, slug=f"s{index}", facts=CONFIRMED_FACTS, status=PublicStatus.open_verified
        )
    first = (await client.post("/api/v1/search", json={**SEARCH, "limit": 2})).json()
    await client.post("/api/v1/search", json={**SEARCH, "limit": 2, "cursor": first["next_cursor"]})

    events = list(await db.scalars(select(OutboxEvent)))
    assert len(events) == 1, "a later page must not inflate the completed-search count"
    assert events[0].event_type == "scholarship_search_completed"
    assert events[0].destination == "posthog"
    assert events[0].state == "pending"


async def test_re_requesting_a_page_does_not_duplicate_history_or_events(db, client) -> None:
    await _publish(db, slug="a", facts=CONFIRMED_FACTS, status=PublicStatus.open_verified)
    await client.post("/api/v1/search", json=SEARCH)
    await client.post("/api/v1/search", json=SEARCH)
    # Two separate submissions are two searches, each with its own page one.
    assert len(list(await db.scalars(select(Search)))) == 2
    assert len(list(await db.scalars(select(OutboxEvent)))) == 2


async def test_the_snapshot_never_carries_a_cursor_or_unlisted_field() -> None:
    """The snapshot is a public-data copy, not an archive of the HTTP response."""
    snapshot = build_result_snapshot(
        [{"name": "Award", "official_url": "https://x.test", "next_cursor": "bearer-token"}],
        evaluated_at=datetime.now(UTC),
        match_policy_version="match-v1",
        taxonomy_version="taxonomy-v1",
        page_number=1,
        requested_limit=20,
        total_match_count=1,
        has_next_page=False,
        warnings=[],
    )
    assert "next_cursor" not in snapshot["data"][0]
    assert snapshot["meta"]["excluded_fields"] == ["next_cursor"]
    assert set(snapshot["data"][0]) <= ALLOWED_RESULT_KEYS
