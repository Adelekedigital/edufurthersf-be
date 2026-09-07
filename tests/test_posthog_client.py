"""`to_posthog_event`'s mapping - pure, no DB or network needed."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from app.domain.models import OutboxEvent
from app.infra.posthog_client import to_posthog_event

_EVENT_ID = UUID("01960000-0000-7000-8000-000000000001")
_CREATED_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _event(**overrides) -> OutboxEvent:
    defaults = dict(
        event_id=_EVENT_ID,
        event_type="thing_happened",
        destination="posthog",
        dedupe_key="dedupe-1",
        payload={},
        state="pending",
        attempts=0,
        created_at=_CREATED_AT,
    )
    return OutboxEvent(**{**defaults, **overrides})


def test_search_completed_uses_its_own_search_id_as_distinct_id() -> None:
    event = _event(
        event_type="scholarship_search_completed", payload={"search_id": "search-abc", "n": 3}
    )
    mapped = to_posthog_event(event)
    assert mapped["distinct_id"] == "search-abc"
    assert mapped["event"] == "scholarship_search_completed"
    assert mapped["properties"] == {"search_id": "search-abc", "n": 3}
    assert mapped["uuid"] == str(_EVENT_ID)
    assert mapped["timestamp"] == "2026-01-01T12:00:00+00:00"


def test_catalog_lifecycle_events_use_a_synthetic_system_distinct_id() -> None:
    event = _event(event_type="scholarship_published", payload={"scholarship_id": "sch-1"})
    assert to_posthog_event(event)["distinct_id"] == "system:sch-1"


def test_unknown_event_type_falls_back_to_a_synthetic_event_scoped_id() -> None:
    event = _event(event_type="something_new", payload={})
    assert to_posthog_event(event)["distinct_id"] == f"system:{_EVENT_ID}"
