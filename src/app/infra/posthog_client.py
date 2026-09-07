"""PostHog batch ingestion.

Sends already-durable `OutboxEvent` rows to PostHog's `/batch/` endpoint. The
batch is accepted or rejected as a whole - PostHog gives no per-event status -
so a caller marks every event in one call's batch dispatched or failed
together, never individually.
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

import httpx

from app.domain.models import OutboxEvent

#: Which OutboxEvent field supplies PostHog's required `distinct_id` per
#: event_type. `scholarship_search_completed` already carries a stable,
#: non-PII per-search id in its own payload. The two catalog-lifecycle
#: events aren't attributed to any searcher, so they get a synthetic,
#: scholarship-scoped id instead of a fabricated person. Add one line here
#: for each new event_type `enqueue_analytics_event` ever gets a new caller
#: for.
_DISTINCT_ID_FIELD: dict[str, str] = {
    "scholarship_search_completed": "search_id",
}


def _distinct_id(event: OutboxEvent) -> str:
    field = _DISTINCT_ID_FIELD.get(event.event_type)
    if field and field in event.payload:
        return str(event.payload[field])
    scholarship_id = event.payload.get("scholarship_id")
    return f"system:{scholarship_id}" if scholarship_id else f"system:{event.event_id}"


def to_posthog_event(event: OutboxEvent) -> dict[str, Any]:
    return {
        "event": event.event_type,
        "distinct_id": _distinct_id(event),
        "properties": event.payload,
        "timestamp": event.created_at.astimezone(UTC).isoformat(),
        # PostHog's own deduplication field - lets a retried delivery of the
        # same batch collapse rather than double-count.
        "uuid": str(event.event_id),
    }


async def send_batch(
    events: list[OutboxEvent], *, api_key: str, host: str, timeout: float = 10.0
) -> None:
    """Send one batch to PostHog. Raises on any non-2xx response."""
    payload = {"api_key": api_key, "batch": [to_posthog_event(event) for event in events]}
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(f"{host.rstrip('/')}/batch/", json=payload)
        response.raise_for_status()
