"""Withdrawing a published record from public results."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import (
    AuditLog,
    PublicStatus,
    RecordState,
    Scholarship,
    ScholarshipCycle,
)
from app.infra.outbox import enqueue_analytics_event


async def withdraw_scholarship(
    db: AsyncSession, scholarship_id: uuid.UUID, *, reason: str, actor: str
) -> int:
    """Withdraw a scholarship and every cycle under it.

    Withdrawal is immediate and does not wait for a sweep: the reason a
    reviewer reaches for it is that the record is actively misleading. Search
    filters on the scholarship's lifecycle state, so flipping it removes the
    record and all of its cycles from results in the same transaction.

    Returns the number of cycles affected.
    """
    scholarship = await db.scalar(
        select(Scholarship).where(Scholarship.scholarship_id == scholarship_id).with_for_update()
    )
    if scholarship is None:
        raise LookupError("Scholarship not found")
    if scholarship.lifecycle_state == RecordState.withdrawn:
        raise ValueError("Scholarship is already withdrawn")

    scholarship.lifecycle_state = RecordState.withdrawn
    cycles = list(
        await db.scalars(
            select(ScholarshipCycle).where(ScholarshipCycle.scholarship_id == scholarship_id)
        )
    )
    for cycle in cycles:
        # A withdrawn record must not keep asserting an open application.
        cycle.public_status = PublicStatus.status_unknown
        cycle.status_valid_until = None

    db.add(
        AuditLog(
            actor=actor,
            action="scholarship.withdrawn",
            target_id=scholarship_id,
            reason=reason[:2000],
        )
    )
    await enqueue_analytics_event(
        db,
        event_type="scholarship_withdrawn",
        dedupe_key=f"withdrawn:{scholarship_id}",
        payload={"scholarship_id": str(scholarship_id), "cycles": len(cycles)},
    )
    await db.flush()
    return len(cycles)
