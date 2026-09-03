"""Publishing an application cycle: the gate between approved and public."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import AuditLog, PublicStatus, RecordState, Scholarship, ScholarshipCycle
from app.infra.outbox import enqueue_analytics_event


async def publish_cycle(
    db: AsyncSession,
    scholarship_id: uuid.UUID,
    *,
    provider_cycle_key: str,
    applicant_segment: str,
    official_cycle_url: str,
    public_status: PublicStatus,
    facts: dict[str, Any],
    status_valid_until: datetime | None,
    last_verified_at: datetime | None,
    actor: str,
) -> ScholarshipCycle:
    """Publish one application cycle.

    This is the record's first public surface, or a further intake added to
    one already published — a new cycle is not a reason to unpublish the last
    one. Refuses only a withdrawn scholarship: reactivating one is a separate,
    explicit reviewer decision this does not make silently.
    """
    scholarship = await db.scalar(
        select(Scholarship).where(Scholarship.scholarship_id == scholarship_id).with_for_update()
    )
    if scholarship is None:
        raise LookupError("Scholarship not found")
    if scholarship.lifecycle_state == RecordState.withdrawn:
        raise ValueError("Cannot publish a withdrawn scholarship")

    existing = await db.scalar(
        select(ScholarshipCycle).where(
            ScholarshipCycle.scholarship_id == scholarship_id,
            ScholarshipCycle.provider_cycle_key == provider_cycle_key,
            ScholarshipCycle.applicant_segment == applicant_segment,
        )
    )
    if existing is not None:
        raise ValueError("A cycle with this key and segment is already published")

    cycle = ScholarshipCycle(
        scholarship_id=scholarship_id,
        provider_cycle_key=provider_cycle_key,
        applicant_segment=applicant_segment,
        official_cycle_url=official_cycle_url,
        public_status=public_status,
        status_valid_until=status_valid_until,
        last_verified_at=last_verified_at,
        facts=facts,
    )
    db.add(cycle)
    scholarship.lifecycle_state = RecordState.published
    db.add(
        AuditLog(
            actor=actor,
            action="scholarship.published",
            target_id=scholarship_id,
            reason=f"cycle {provider_cycle_key} ({applicant_segment}) published",
        )
    )
    await db.flush()
    await enqueue_analytics_event(
        db,
        event_type="scholarship_published",
        dedupe_key=f"published:{scholarship_id}:{provider_cycle_key}:{applicant_segment}",
        payload={
            "scholarship_id": str(scholarship_id),
            "cycle_id": str(cycle.cycle_id),
            "provider_cycle_key": provider_cycle_key,
        },
    )
    return cycle
