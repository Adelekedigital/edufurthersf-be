"""Searching and filtering scholarships for admin/testing use.

Distinct from the public `/search` route: no destination/level/field
matching, no session or rate limiting, and every lifecycle state is visible -
this is for a reviewer or tester confirming what actually landed, not for an
applicant.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.models import PublicStatus, RecordState, Scholarship, ScholarshipCycle


def _escape_ilike(term: str) -> str:
    """Treat `%` and `_` in a search term literally rather than as wildcards."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _filters(
    *,
    q: str | None,
    lifecycle_state: RecordState | None,
    provider_id: uuid.UUID | None,
    public_status: PublicStatus | None,
) -> tuple:
    predicates: list = []
    if q:
        predicates.append(Scholarship.name.ilike(f"%{_escape_ilike(q)}%", escape="\\"))
    if lifecycle_state is not None:
        predicates.append(Scholarship.lifecycle_state == lifecycle_state)
    if provider_id is not None:
        predicates.append(Scholarship.provider_id == provider_id)
    if public_status is not None:
        predicates.append(
            Scholarship.cycles.any(ScholarshipCycle.public_status == public_status)
        )
    return tuple(predicates)


async def search_scholarships(
    db: AsyncSession,
    *,
    q: str | None = None,
    lifecycle_state: RecordState | None = None,
    provider_id: uuid.UUID | None = None,
    public_status: PublicStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Scholarship], int]:
    predicates = _filters(
        q=q, lifecycle_state=lifecycle_state, provider_id=provider_id, public_status=public_status
    )
    total = await db.scalar(
        select(func.count(func.distinct(Scholarship.scholarship_id))).where(*predicates)
    )
    rows = list(
        await db.scalars(
            select(Scholarship)
            .where(*predicates)
            .options(selectinload(Scholarship.provider), selectinload(Scholarship.cycles))
            .order_by(Scholarship.updated_at.desc(), Scholarship.scholarship_id)
            .limit(limit)
            .offset(offset)
        )
    )
    return rows, int(total or 0)
