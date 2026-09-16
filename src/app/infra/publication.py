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


async def load_cycle_for_update(
    db: AsyncSession, scholarship_id: uuid.UUID, cycle_id: uuid.UUID
) -> ScholarshipCycle:
    """Return one cycle, locked, ready to be corrected.

    Scoped to its scholarship rather than looked up by `cycle_id` alone: a
    caller that has the wrong parent has made a mistake worth a 404, not a
    silent edit of a cycle belonging to another record.

    Refuses a withdrawn scholarship for the same reason `publish_cycle` does.
    Editing what was pulled from public results is not a way to bring it
    back; reactivating one is a separate, explicit decision.
    """
    scholarship = await db.scalar(
        select(Scholarship).where(Scholarship.scholarship_id == scholarship_id).with_for_update()
    )
    if scholarship is None:
        raise LookupError("Scholarship not found")
    if scholarship.lifecycle_state == RecordState.withdrawn:
        raise ValueError("Cannot update a cycle of a withdrawn scholarship")

    cycle = await db.scalar(
        select(ScholarshipCycle).where(
            ScholarshipCycle.cycle_id == cycle_id,
            ScholarshipCycle.scholarship_id == scholarship_id,
        )
    )
    if cycle is None:
        raise LookupError("Cycle not found")
    return cycle


async def update_cycle(
    db: AsyncSession,
    cycle: ScholarshipCycle,
    *,
    provider_cycle_key: str,
    applicant_segment: str,
    official_cycle_url: str,
    public_status: PublicStatus,
    facts: dict[str, Any],
    status_valid_until: datetime | None,
    last_verified_at: datetime | None,
    changed_fields: list[str],
    actor: str,
) -> ScholarshipCycle:
    """Apply a correction to one published cycle.

    The identity triple is re-checked before writing: it is unique at the
    database level, so renaming a cycle onto one that already exists has to
    fail as a 409 here rather than as an IntegrityError at commit.

    `evaluated_public_status` is not touched - it is recomputed from the
    stored values on every read (`domain/status.py`), so correcting a
    deadline or a validity window takes effect on the next read with nothing
    to re-run here.
    """
    identity_changed = (
        provider_cycle_key != cycle.provider_cycle_key
        or applicant_segment != cycle.applicant_segment
    )
    if identity_changed:
        clash = await db.scalar(
            select(ScholarshipCycle).where(
                ScholarshipCycle.scholarship_id == cycle.scholarship_id,
                ScholarshipCycle.provider_cycle_key == provider_cycle_key,
                ScholarshipCycle.applicant_segment == applicant_segment,
                ScholarshipCycle.cycle_id != cycle.cycle_id,
            )
        )
        if clash is not None:
            raise ValueError("A cycle with this key and segment is already published")

    cycle.provider_cycle_key = provider_cycle_key
    cycle.applicant_segment = applicant_segment
    cycle.official_cycle_url = official_cycle_url
    cycle.public_status = public_status
    cycle.status_valid_until = status_valid_until
    cycle.last_verified_at = last_verified_at
    cycle.facts = facts

    db.add(
        AuditLog(
            actor=actor,
            action="scholarship.cycle_updated",
            target_id=cycle.scholarship_id,
            reason=f"cycle {provider_cycle_key} ({applicant_segment}) updated",
            # Which fields moved, so a later audit of a live listing that
            # changed under its users does not have to diff two snapshots to
            # find out what a reviewer actually touched.
            context={"cycle_id": str(cycle.cycle_id), "changed_fields": sorted(changed_fields)},
        )
    )
    await db.flush()
    return cycle
