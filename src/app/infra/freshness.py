"""The two freshness jobs: `refresh_status` (pure recompute, no network) and
`reverify_due` (actual re-fetch + deterministic hash recheck).

Both scan the published cycle set the same way `/search` does
(`Scholarship.lifecycle_state == RecordState.published`) and share one
evidence-staleness bound (`_evidence_deadline`) so a downgrade `refresh_status`
writes and an escalation `reverify_due` opens are never computed two
different ways.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.domain.facts import derive_facts
from app.domain.freshness import (
    FreshnessBucket,
    FreshnessConfig,
    classify_bucket,
    is_reverify_due,
    is_unchanged_recheck,
    max_evidence_age,
)
from app.domain.models import (
    PublicStatus,
    RecordState,
    ReviewTask,
    ScholarshipCycle,
    Source,
    SourcePage,
)
from app.domain.status import deadline_cutoff, evaluate_public_status
from app.domain.urls import canonicalize_url
from app.infra.source_persistence import fetch_and_persist_page

logger = logging.getLogger("app.infra.freshness")

#: The one-time operational step (POST /internal/admin/sources, or
#: scripts/create_official_cycle_source.py) that must create this row
#: before reverify_due can fetch anything. Looked up by name rather than a
#: hardcoded id so it survives being recreated in a fresh environment.
OFFICIAL_SOURCE_NAME = "Official Cycle Pages"

#: A generous safety net, not a real limiter at launch scale (~100
#: published cycles) - PUBLISHED_CYCLE_SCAN_LIMIT in api/routes.py serves
#: the same role for /search; this is infra/'s own copy rather than an
#: import from api/, which would invert this project's layering.
_PUBLISHED_CYCLE_SCAN_LIMIT = 5000


def _freshness_config(settings: Settings) -> FreshnessConfig:
    return FreshnessConfig(
        near_deadline_days=settings.freshness_near_deadline_days,
        upcoming_near_months=settings.freshness_upcoming_near_months,
        upcoming_far_months=settings.freshness_upcoming_far_months,
        open_far_fetch_hours=settings.freshness_open_far_fetch_hours,
        open_far_max_age_hours=settings.freshness_open_far_max_age_hours,
        open_near_fetch_hours=settings.freshness_open_near_fetch_hours,
        open_near_max_age_hours=settings.freshness_open_near_max_age_hours,
        rolling_fetch_hours=settings.freshness_rolling_fetch_hours,
        rolling_max_age_hours=settings.freshness_rolling_max_age_hours,
        upcoming_near_fetch_hours=settings.freshness_upcoming_near_fetch_hours,
        upcoming_far_fetch_hours=settings.freshness_upcoming_far_fetch_hours,
        upcoming_max_age_hours=settings.freshness_upcoming_max_age_hours,
        unknown_fetch_hours=settings.freshness_unknown_fetch_hours,
        unknown_max_age_hours=settings.freshness_unknown_max_age_hours,
        closed_fetch_hours=settings.freshness_closed_fetch_hours,
        closed_max_age_hours=settings.freshness_closed_max_age_hours,
    )


def _evidence_deadline(
    cycle: ScholarshipCycle, bucket: FreshnessBucket, cfg: FreshnessConfig
) -> datetime:
    """The instant this cycle's current evidence goes stale.

    Anchored on `last_verified_at` once there's ever been a confirmed
    recheck; before that, anchored on `created_at` - a cycle that has never
    been reverified isn't "stale," it just hasn't had its first chance yet.
    Anchoring a never-verified cycle on `now` instead would make every
    freshly published cycle stale (and every first reverify_due encounter
    an immediate escalation) the moment either job first runs.
    """
    anchor = cycle.last_verified_at or cycle.created_at
    return anchor + max_evidence_age(bucket, cfg)


async def _published_cycles(
    db: AsyncSession, *, limit: int, lock: bool
) -> list[ScholarshipCycle]:
    query = (
        select(ScholarshipCycle)
        .join(ScholarshipCycle.scholarship)
        .where(ScholarshipCycle.scholarship.has(lifecycle_state=RecordState.published))
        .order_by(ScholarshipCycle.cycle_id)
        .limit(limit)
    )
    if lock:
        query = query.with_for_update(of=ScholarshipCycle, skip_locked=True)
    result = await db.execute(query)
    return list(result.scalars().all())


async def refresh_due_statuses(db: AsyncSession, *, limit: int | None = None) -> dict[str, int]:
    """Re-evaluate `public_status` from already-stored facts. No fetch.

    Writes `status_valid_until` on every checked open_verified cycle
    (whether or not it downgrades this tick) so a read-time
    `evaluate_public_status` call stays self-correcting between sweeps even
    if the next scheduled tick is delayed. Never opens a `ReviewTask`:
    `reverify_due` runs on the same cadence and is what actually resolves a
    stale record, either silently (an unchanged-content auto-renew) or by
    escalating with a real signal - flagging every time-elapsed downgrade
    here too would duplicate that and flood the queue with non-problems.
    """
    settings = get_settings()
    cfg = _freshness_config(settings)
    batch_limit = limit if limit is not None else settings.refresh_status_batch_limit
    now = datetime.now(UTC)

    cycles = await _published_cycles(db, limit=batch_limit, lock=True)
    checked = 0
    downgraded = 0
    for cycle in cycles:
        checked += 1
        facts = cycle.facts or {}
        derived = derive_facts(facts)
        bucket = classify_bucket(
            cycle.public_status,
            deadline_at=derived.deadline_at,
            deadline_precision=derived.deadline_precision,
            deadline_timezone=derived.deadline_timezone,
            expected_reopen_month=derived.expected_reopen_month,
            now=now,
            cfg=cfg,
        )
        evaluated = evaluate_public_status(
            cycle.public_status,
            deadline_at=derived.deadline_at,
            deadline_precision=derived.deadline_precision,
            deadline_timezone=derived.deadline_timezone,
            status_valid_until=cycle.status_valid_until,
            now=now,
        )
        stale = _evidence_deadline(cycle, bucket, cfg) <= now
        # The cadence table (section 8) only says "downgrade" for the Open
        # rows; the Expected/Unknown rows say "review" instead - an
        # already-uncertain status going stale means it's due for
        # reverify_due's escalation (which isn't scoped to any one status),
        # not a forced flip to status_unknown here.
        target_status = cycle.public_status
        if evaluated == PublicStatus.status_unknown:
            target_status = PublicStatus.status_unknown
        elif cycle.public_status == PublicStatus.open_verified and stale:
            target_status = PublicStatus.status_unknown
        if cycle.public_status == PublicStatus.open_verified:
            candidates = [_evidence_deadline(cycle, bucket, cfg)]
            if derived.deadline_at is not None:
                candidates.append(
                    deadline_cutoff(
                        derived.deadline_at,
                        precision=derived.deadline_precision,
                        timezone=derived.deadline_timezone,
                    )
                )
            new_valid_until = min(candidates)
            if cycle.status_valid_until != new_valid_until:
                cycle.status_valid_until = new_valid_until
        if target_status != cycle.public_status:
            logger.info(
                "status_downgraded",
                extra={
                    "cycle_id": str(cycle.cycle_id),
                    "from_status": cycle.public_status.value,
                    "to_status": target_status.value,
                    "bucket": bucket.value,
                },
            )
            cycle.public_status = target_status
            downgraded += 1
    await db.commit()
    return {"checked": checked, "downgraded": downgraded}


async def _open_cycle_review_task(
    db: AsyncSession, cycle: ScholarshipCycle, *, reason: str, draft: dict
) -> bool:
    """Idempotent insert, mirroring `linking.py::_add_review_task_once` -
    `uq_review_tasks_open_per_cycle` (migration 0021) is the real
    concurrency guard; this check-then-insert is just the fast path."""
    inserted = await db.execute(
        insert(ReviewTask)
        .values(cycle_id=cycle.cycle_id, reason=reason[:255], draft_recommendation=draft)
        .on_conflict_do_nothing(
            index_elements=["cycle_id"],
            index_where=text("state = 'open' AND resolution IS NULL"),
        )
        .returning(ReviewTask.review_task_id)
    )
    return inserted.scalar_one_or_none() is not None


async def _get_or_create_source_page(
    db: AsyncSession, source_id: uuid.UUID, cycle: ScholarshipCycle
) -> SourcePage:
    if cycle.source_page_id is not None:
        existing = await db.get(SourcePage, cycle.source_page_id)
        if existing is not None:
            return existing
    normalized_url = canonicalize_url(cycle.official_cycle_url)
    page = await db.scalar(
        select(SourcePage).where(
            SourcePage.source_id == source_id, SourcePage.normalized_url == normalized_url
        )
    )
    if page is None:
        page = SourcePage(source_id=source_id, normalized_url=normalized_url)
        db.add(page)
        await db.flush()
    cycle.source_page_id = page.page_id
    return page


async def reverify_due_cycles(db: AsyncSession, *, limit: int | None = None) -> dict[str, int]:
    """Re-fetch each due cycle's official page and deterministically compare
    its content hash to the last known one (data-verification standard
    section 4). Renews `last_verified_at` on an unchanged match; opens a
    `ReviewTask` on a real signal (content changed, or the evidence age
    bound has elapsed without ever confirming unchanged) - never on a
    single failed or first-ever fetch alone.
    """
    settings = get_settings()
    cfg = _freshness_config(settings)
    batch_limit = limit if limit is not None else settings.reverify_due_batch_limit
    now = datetime.now(UTC)

    source = await db.scalar(select(Source).where(Source.name == OFFICIAL_SOURCE_NAME))
    if source is None or not source.active:
        logger.warning(
            "reverify_due_official_source_missing", extra={"source_name": OFFICIAL_SOURCE_NAME}
        )
        return {"checked": 0, "renewed": 0, "flagged": 0, "deferred": 0}
    # A plain value, not the ORM object: a later iteration's db.rollback()
    # (after a prior cycle's unexpected failure) expires every object the
    # session is still tracking, including one loaded before this loop -
    # a bare attribute read on an expired object outside an explicit await
    # triggers an implicit lazy-load that MissingGreenlets. source_id has no
    # such lazy-loading behavior to trip over.
    source_id = source.source_id

    candidates = await _published_cycles(db, limit=_PUBLISHED_CYCLE_SCAN_LIMIT, lock=False)
    due_cycle_ids = []
    for cycle in candidates:
        derived = derive_facts(cycle.facts or {})
        bucket = classify_bucket(
            cycle.public_status,
            deadline_at=derived.deadline_at,
            deadline_precision=derived.deadline_precision,
            deadline_timezone=derived.deadline_timezone,
            expected_reopen_month=derived.expected_reopen_month,
            now=now,
            cfg=cfg,
        )
        if is_reverify_due(bucket, last_verified_at=cycle.last_verified_at, now=now, cfg=cfg):
            due_cycle_ids.append(cycle.cycle_id)
        if len(due_cycle_ids) >= batch_limit:
            break

    checked = renewed = flagged = deferred = 0
    for cycle_id in due_cycle_ids:
        due_cycle = await db.scalar(
            select(ScholarshipCycle)
            .where(ScholarshipCycle.cycle_id == cycle_id)
            .with_for_update()
        )
        if due_cycle is None:
            continue
        checked += 1
        try:
            outcome = await _reverify_one_cycle(db, source_id, due_cycle, cfg=cfg, now=now)
        except Exception:
            logger.exception("reverify_due_cycle_failed", extra={"cycle_id": str(cycle_id)})
            await db.rollback()
            continue
        if outcome == "renewed":
            renewed += 1
        elif outcome == "flagged":
            flagged += 1
        else:
            deferred += 1
        await db.commit()
    return {"checked": checked, "renewed": renewed, "flagged": flagged, "deferred": deferred}


async def _reverify_one_cycle(
    db: AsyncSession,
    source_id: uuid.UUID,
    cycle: ScholarshipCycle,
    *,
    cfg: FreshnessConfig,
    now: datetime,
) -> str:
    """Returns "renewed", "flagged" or "deferred" - never raises for an
    ordinary fetch failure, only for something the caller should log and
    move past (an unexpected DB error, say)."""
    page = await _get_or_create_source_page(db, source_id, cycle)
    previous_hash = page.normalized_content_hash
    hostname = urlsplit(page.normalized_url).hostname or ""
    try:
        # fetch_and_persist_page commits internally, ending this call's
        # share of the outer with_for_update lock on `cycle` a little early.
        # Acceptable: the quarter-hour dedupe key already keeps two runs of
        # this same job kind from overlapping, and the worst case of a rare
        # concurrent hit is a harmless duplicate fetch - SourcePage's own
        # unique constraint and uq_review_tasks_open_per_cycle still prevent
        # any actual duplicate write.
        await fetch_and_persist_page(db, page.page_id, approved_domains_override=[hostname])
    except Exception as exc:
        logger.warning(
            "reverify_fetch_failed", extra={"cycle_id": str(cycle.cycle_id), "error": str(exc)}
        )
        return await _defer_or_flag(db, cycle, cfg=cfg, now=now, reason="reverify_fetch_failed")

    await db.refresh(page)
    new_hash = page.normalized_content_hash
    fetch_ok = (
        new_hash is not None and page.http_status is not None and 200 <= page.http_status < 400
    )

    derived = derive_facts(cycle.facts or {})
    evaluated_now = evaluate_public_status(
        cycle.public_status,
        deadline_at=derived.deadline_at,
        deadline_precision=derived.deadline_precision,
        deadline_timezone=derived.deadline_timezone,
        status_valid_until=cycle.status_valid_until,
        now=now,
    )
    status_still_valid = evaluated_now == cycle.public_status

    if previous_hash is None or not fetch_ok or new_hash is None:
        return await _defer_or_flag(
            db,
            cycle,
            cfg=cfg,
            now=now,
            reason="reverify_link_unreachable" if not fetch_ok else "reverify_first_observation",
        )

    if is_unchanged_recheck(
        previous_hash=previous_hash,
        new_hash=new_hash,
        http_status=page.http_status or 0,
        status_still_valid=status_still_valid,
    ):
        cycle.last_verified_at = now
        return "renewed"

    await _open_cycle_review_task(
        db,
        cycle,
        reason="reverify_content_changed",
        draft={
            "cycle_id": str(cycle.cycle_id),
            "official_cycle_url": cycle.official_cycle_url,
            "previous_content_hash": previous_hash,
            "new_content_hash": new_hash,
        },
    )
    return "flagged"


async def _defer_or_flag(
    db: AsyncSession, cycle: ScholarshipCycle, *, cfg: FreshnessConfig, now: datetime, reason: str
) -> str:
    """A single failed or first-ever fetch is never itself a reason to
    escalate - only the same evidence-age bound `refresh_status` uses,
    elapsed with no successful confirmation, is."""
    derived = derive_facts(cycle.facts or {})
    bucket = classify_bucket(
        cycle.public_status,
        deadline_at=derived.deadline_at,
        deadline_precision=derived.deadline_precision,
        deadline_timezone=derived.deadline_timezone,
        expected_reopen_month=derived.expected_reopen_month,
        now=now,
        cfg=cfg,
    )
    if _evidence_deadline(cycle, bucket, cfg) > now:
        return "deferred"
    await _open_cycle_review_task(
        db,
        cycle,
        reason=reason,
        draft={
            "cycle_id": str(cycle.cycle_id),
            "official_cycle_url": cycle.official_cycle_url,
        },
    )
    return "flagged"
