"""The freshness/re-verification cadence table (data-verification standard
section 8) as pure, DB- and vendor-free code.

`FreshnessConfig` carries every tunable value; nothing here reads
`Settings`/`pydantic_settings` directly (see `infra/freshness.py` for the
conversion) so this stays testable with plain dataclasses and easy to keep
vendor-free per this project's layering rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal

from app.domain.models import PublicStatus
from app.domain.status import deadline_cutoff


class FreshnessBucket(StrEnum):
    open_far = "open_far"  # Open, deadline more than N days away
    open_near = "open_near"  # Open, deadline within N days
    rolling_open = "rolling_open"  # Open, no deadline
    upcoming_near = "upcoming_near"  # Announced, opening imminent
    upcoming_far = "upcoming_far"  # Announced, within the near-term window
    expected_or_unknown = "expected_or_unknown"  # Expected outside that window, or status unknown
    #: No published cycle can reach this today - PublicStatus has no
    #: CLOSED/CANCELLED value, so `classify_bucket` never returns it. Kept
    #: so the cadence table and its config fields are ready for that value
    #: once it exists, rather than needing a second migration then too.
    closed_archive = "closed_archive"


@dataclass(frozen=True)
class FreshnessConfig:
    #: Bucket-boundary thresholds, not just the cadence values themselves -
    #: per the data-verification standard's own instruction against cron
    #: literals/thresholds hardcoded in application modules.
    near_deadline_days: int
    upcoming_near_months: int
    upcoming_far_months: int

    open_far_fetch_hours: int
    open_far_max_age_hours: int
    open_near_fetch_hours: int
    open_near_max_age_hours: int
    rolling_fetch_hours: int
    rolling_max_age_hours: int
    upcoming_near_fetch_hours: int
    upcoming_far_fetch_hours: int
    upcoming_max_age_hours: int
    unknown_fetch_hours: int
    unknown_max_age_hours: int
    closed_fetch_hours: int
    closed_max_age_hours: int


_FETCH_HOURS_FIELD: dict[FreshnessBucket, str] = {
    FreshnessBucket.open_far: "open_far_fetch_hours",
    FreshnessBucket.open_near: "open_near_fetch_hours",
    FreshnessBucket.rolling_open: "rolling_fetch_hours",
    FreshnessBucket.upcoming_near: "upcoming_near_fetch_hours",
    FreshnessBucket.upcoming_far: "upcoming_far_fetch_hours",
    FreshnessBucket.expected_or_unknown: "unknown_fetch_hours",
    FreshnessBucket.closed_archive: "closed_fetch_hours",
}

_MAX_AGE_HOURS_FIELD: dict[FreshnessBucket, str] = {
    FreshnessBucket.open_far: "open_far_max_age_hours",
    FreshnessBucket.open_near: "open_near_max_age_hours",
    FreshnessBucket.rolling_open: "rolling_max_age_hours",
    FreshnessBucket.upcoming_near: "upcoming_max_age_hours",
    FreshnessBucket.upcoming_far: "upcoming_max_age_hours",
    FreshnessBucket.expected_or_unknown: "unknown_max_age_hours",
    FreshnessBucket.closed_archive: "closed_max_age_hours",
}


def fetch_interval(bucket: FreshnessBucket, cfg: FreshnessConfig) -> timedelta:
    return timedelta(hours=getattr(cfg, _FETCH_HOURS_FIELD[bucket]))


def max_evidence_age(bucket: FreshnessBucket, cfg: FreshnessConfig) -> timedelta:
    return timedelta(hours=getattr(cfg, _MAX_AGE_HOURS_FIELD[bucket]))


def classify_bucket(
    public_status: PublicStatus,
    *,
    deadline_at: datetime | None,
    deadline_precision: Literal["date", "datetime"],
    deadline_timezone: str | None,
    expected_reopen_month: int | None,
    now: datetime,
    cfg: FreshnessConfig,
) -> FreshnessBucket:
    """Bucket one cycle into the data-verification standard's section 8 table.

    The reopen-month tiers are a documented approximation, not an invented
    day-precision cutoff: `facts` only ever carries `expected_reopen_month`
    at month granularity (deliberately - the data standard forbids turning
    an average into an exact promised date), so "opening within 7 days" vs
    "within 60 days" is approximated with the same months-until-reopen
    heuristic `evaluate_status_detail` already uses for its "likely_to_open"
    display label, rather than inventing a second, disagreeing threshold
    for the same underlying signal.
    """
    if public_status == PublicStatus.open_verified:
        if deadline_at is None:
            return FreshnessBucket.rolling_open
        cutoff = deadline_cutoff(
            deadline_at, precision=deadline_precision, timezone=deadline_timezone
        )
        if cutoff - now <= timedelta(days=cfg.near_deadline_days):
            return FreshnessBucket.open_near
        return FreshnessBucket.open_far
    if public_status == PublicStatus.expected_to_reopen and expected_reopen_month is not None:
        months_until_reopen = (expected_reopen_month - now.month) % 12
        if months_until_reopen <= cfg.upcoming_near_months:
            return FreshnessBucket.upcoming_near
        if months_until_reopen <= cfg.upcoming_far_months:
            return FreshnessBucket.upcoming_far
    return FreshnessBucket.expected_or_unknown


def is_reverify_due(
    bucket: FreshnessBucket,
    *,
    last_verified_at: datetime | None,
    now: datetime,
    cfg: FreshnessConfig,
) -> bool:
    if last_verified_at is None:
        return True
    return now - last_verified_at >= fetch_interval(bucket, cfg)


def is_unchanged_recheck(
    *,
    previous_hash: str | None,
    new_hash: str,
    http_status: int,
    status_still_valid: bool,
) -> bool:
    """The section 4 deterministic-unchanged-evidence-recheck rule: the same
    approved page fetched successfully, the same hash, and status rules
    still pass. `previous_hash is None` means this is the cycle's first-ever
    fetch - nothing to compare against, so never "unchanged"."""
    if previous_hash is None:
        return False
    if not (200 <= http_status < 400):
        return False
    if new_hash != previous_hash:
        return False
    return status_still_valid
