"""`refresh_status`: pure recompute of public_status from stored facts, no
network. No ReviewTask is ever created here - reverify_due (a separate
job) owns escalation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.domain.models import (
    Provider,
    PublicStatus,
    RecordState,
    ReviewTask,
    Scholarship,
    ScholarshipCycle,
)
from app.infra.freshness import refresh_due_statuses
from tests.conftest import requires_db

pytestmark = requires_db

NOW = datetime.now(UTC)


async def _publish(
    db,
    *,
    slug: str = "award-a",
    public_status: PublicStatus = PublicStatus.open_verified,
    facts: dict | None = None,
    last_verified_at: datetime | None = None,
    created_at: datetime | None = None,
    status_valid_until: datetime | None = None,
) -> ScholarshipCycle:
    provider = Provider(name="Example University", approved_domains=["example.test"])
    db.add(provider)
    await db.flush()
    scholarship = Scholarship(
        provider_id=provider.provider_id,
        slug=slug,
        name="Award A",
        official_home_url="https://example.test/award",
        award_type="scholarship",
        lifecycle_state=RecordState.published,
    )
    db.add(scholarship)
    await db.flush()
    cycle = ScholarshipCycle(
        scholarship_id=scholarship.scholarship_id,
        provider_cycle_key=f"{slug}-2026",
        official_cycle_url="https://example.test/award/apply",
        public_status=public_status,
        facts=facts or {},
        last_verified_at=last_verified_at,
        status_valid_until=status_valid_until,
    )
    db.add(cycle)
    await db.commit()
    await db.refresh(cycle)
    if created_at is not None:
        cycle.created_at = created_at
        await db.commit()
        await db.refresh(cycle)
    return cycle


async def test_a_freshly_verified_open_cycle_is_not_downgraded(db) -> None:
    cycle = await _publish(db, last_verified_at=NOW)
    result = await refresh_due_statuses(db)
    assert result == {"checked": 1, "downgraded": 0}
    await db.refresh(cycle)
    assert cycle.public_status == PublicStatus.open_verified
    # rolling_open (no deadline): max_age default is 48h from last_verified_at.
    assert cycle.status_valid_until == NOW + timedelta(hours=48)


async def test_running_it_twice_in_a_row_does_not_rewrite_an_unchanged_value(db) -> None:
    cycle = await _publish(db, last_verified_at=NOW)
    await refresh_due_statuses(db)
    await db.refresh(cycle)
    first_valid_until = cycle.status_valid_until

    await refresh_due_statuses(db)
    await db.refresh(cycle)
    assert cycle.status_valid_until == first_valid_until


async def test_a_never_verified_but_freshly_published_cycle_is_not_downgraded(db) -> None:
    """Anchored on created_at, not `now` - a brand-new cycle isn't stale just
    because it has never been reverified yet."""
    cycle = await _publish(db, last_verified_at=None, created_at=NOW)
    result = await refresh_due_statuses(db)
    assert result == {"checked": 1, "downgraded": 0}
    await db.refresh(cycle)
    assert cycle.public_status == PublicStatus.open_verified


async def test_a_cycle_whose_evidence_has_gone_stale_is_downgraded(db) -> None:
    stale_verification = NOW - timedelta(hours=72)  # past the 48h rolling_open bound
    cycle = await _publish(db, last_verified_at=stale_verification)
    result = await refresh_due_statuses(db)
    assert result == {"checked": 1, "downgraded": 1}
    await db.refresh(cycle)
    assert cycle.public_status == PublicStatus.status_unknown


async def test_a_cycle_past_its_deadline_is_downgraded_even_if_recently_verified(db) -> None:
    past_deadline = (NOW - timedelta(days=1)).isoformat()
    cycle = await _publish(
        db, last_verified_at=NOW, facts={"deadline_at": past_deadline, "deadline_precision": "date"}
    )
    result = await refresh_due_statuses(db)
    assert result["downgraded"] == 1
    await db.refresh(cycle)
    assert cycle.public_status == PublicStatus.status_unknown


async def test_downgrading_never_creates_a_review_task(db) -> None:
    stale_verification = NOW - timedelta(hours=72)
    await _publish(db, last_verified_at=stale_verification)
    await refresh_due_statuses(db)
    tasks = list(await db.scalars(select(ReviewTask)))
    assert tasks == []


async def test_a_non_open_cycle_status_valid_until_is_left_alone(db) -> None:
    """status_valid_until only matters to evaluate_public_status for a
    stored open_verified status - no need to churn it for anything else."""
    cycle = await _publish(
        db,
        public_status=PublicStatus.expected_to_reopen,
        last_verified_at=NOW - timedelta(days=400),
        status_valid_until=None,
    )
    await refresh_due_statuses(db)
    await db.refresh(cycle)
    assert cycle.public_status == PublicStatus.expected_to_reopen
    assert cycle.status_valid_until is None


async def test_already_downgraded_cycles_are_reported_but_not_recounted_as_new(db) -> None:
    cycle = await _publish(
        db, public_status=PublicStatus.status_unknown, last_verified_at=NOW - timedelta(hours=72)
    )
    result = await refresh_due_statuses(db)
    assert result == {"checked": 1, "downgraded": 0}
    await db.refresh(cycle)
    assert cycle.public_status == PublicStatus.status_unknown


async def test_batch_limit_bounds_how_many_cycles_one_tick_checks(db) -> None:
    for i in range(3):
        await _publish(db, slug=f"award-{i}", last_verified_at=NOW)
    result = await refresh_due_statuses(db, limit=2)
    assert result["checked"] == 2
