"""Durable event delivery.

An analytics event is written in the same transaction as the business change it
describes, so a vendor outage or a crash after the commit cannot lose it and a
rolled-back search cannot announce one that never happened. Dispatch happens
later, out of the request path: search must never wait on an analytics vendor.

Consumers are filtered by `destination`. The row shape is shared, so a consumer
that reads the table without filtering would pick up rows meant for another
destination — analytics events must never reach an email sender.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.ids import new_uuid7
from app.domain.models import OutboxEvent
from app.infra.posthog_client import send_batch

logger = logging.getLogger("app.infra.outbox")

#: Analytics destination. PostHog is the chosen platform.
DESTINATION_ANALYTICS = "posthog"

MAX_DISPATCH_ATTEMPTS = 5


async def enqueue_analytics_event(
    db: AsyncSession,
    *,
    event_type: str,
    dedupe_key: str,
    payload: dict[str, Any],
) -> None:
    """Record one analytics event for later dispatch.

    Flushed, not committed: the caller's transaction decides whether both the
    business change and this event become durable together.

    `dedupe_key` makes a retried request idempotent. A repeated page-one
    response must not manufacture a second completed-search conversion.
    """
    await db.execute(
        insert(OutboxEvent)
        .values(
            event_id=new_uuid7(),
            event_type=event_type,
            destination=DESTINATION_ANALYTICS,
            dedupe_key=dedupe_key,
            payload=payload,
            state="pending",
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
    )


async def claim_pending_events(
    db: AsyncSession, *, destination: str, limit: int = 100
) -> list[OutboxEvent]:
    """Take a bounded batch of undelivered events for one destination."""
    rows = await db.scalars(
        select(OutboxEvent)
        .where(
            OutboxEvent.destination == destination,
            OutboxEvent.state == "pending",
            OutboxEvent.attempts < MAX_DISPATCH_ATTEMPTS,
        )
        .order_by(OutboxEvent.event_id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(rows)


async def dispatch_analytics_events(db: AsyncSession, *, limit: int = 100) -> dict[str, int]:
    """Dispatch pending analytics events.

    Both the environment gate (`posthog_dispatch_active` - off by default in
    local development even once a key exists, see `Settings`) and a
    configured API key are required before anything is actually sent.
    Without either, events are held rather than sent: marking them delivered
    here would destroy the record the dispatcher exists to protect, and
    dropping them would lose it, so they stay pending and visible.

    PostHog's batch endpoint accepts or rejects the whole batch, not
    individual events, so every event in one call's batch is marked
    dispatched - or failed - together.
    """
    settings = get_settings()
    events = await claim_pending_events(db, destination=DESTINATION_ANALYTICS, limit=limit)
    if not (settings.posthog_dispatch_active and settings.posthog_api_key):
        held = len(events)
        await db.commit()
        return {"held": held, "dispatched": 0}
    if not events:
        await db.commit()
        return {"held": 0, "dispatched": 0}
    try:
        await send_batch(events, api_key=settings.posthog_api_key, host=settings.posthog_host)
    except httpx.HTTPError as exc:
        logger.warning(
            "posthog_dispatch_failed", extra={"batch_size": len(events), "error": str(exc)[:500]}
        )
        for event in events:
            await mark_failed(db, event, str(exc))
        await db.commit()
        return {"held": 0, "dispatched": 0, "failed": len(events)}
    for event in events:
        await mark_dispatched(db, event)
    await db.commit()
    return {"held": 0, "dispatched": len(events)}


async def mark_dispatched(db: AsyncSession, event: OutboxEvent) -> None:
    event.state = "dispatched"
    event.dispatched_at = datetime.now(UTC)


async def mark_failed(db: AsyncSession, event: OutboxEvent, error: str) -> None:
    event.attempts += 1
    if event.attempts >= MAX_DISPATCH_ATTEMPTS:
        # Exhausted work stays visible for an operator to replay rather than
        # being retried forever or silently discarded.
        event.state = "dead_letter"
    event.payload = {**event.payload, "last_error": error[:500]}
