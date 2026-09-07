"""Pure unit tests for the freshness cadence table (domain/freshness.py) -
no DB, no network."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domain.freshness import (
    FreshnessBucket,
    FreshnessConfig,
    classify_bucket,
    fetch_interval,
    is_reverify_due,
    is_unchanged_recheck,
    max_evidence_age,
)
from app.domain.models import PublicStatus

NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)

CFG = FreshnessConfig(
    near_deadline_days=14,
    upcoming_near_months=1,
    upcoming_far_months=2,
    open_far_fetch_hours=24,
    open_far_max_age_hours=48,
    open_near_fetch_hours=6,
    open_near_max_age_hours=12,
    rolling_fetch_hours=24,
    rolling_max_age_hours=48,
    upcoming_near_fetch_hours=24,
    upcoming_far_fetch_hours=168,
    upcoming_max_age_hours=336,
    unknown_fetch_hours=720,
    unknown_max_age_hours=720,
    closed_fetch_hours=2160,
    closed_max_age_hours=2160,
)


def _classify(**overrides):
    defaults = dict(
        public_status=PublicStatus.open_verified,
        deadline_at=None,
        deadline_precision="datetime",
        deadline_timezone=None,
        expected_reopen_month=None,
        now=NOW,
        cfg=CFG,
    )
    return classify_bucket(**{**defaults, **overrides})


def test_open_with_no_deadline_is_rolling_open() -> None:
    assert _classify() == FreshnessBucket.rolling_open


def test_open_with_a_far_deadline_is_open_far() -> None:
    deadline = NOW + timedelta(days=30)
    assert _classify(deadline_at=deadline) == FreshnessBucket.open_far


def test_open_with_a_near_deadline_is_open_near() -> None:
    deadline = NOW + timedelta(days=5)
    assert _classify(deadline_at=deadline) == FreshnessBucket.open_near


def test_deadline_exactly_at_the_near_boundary_is_open_near() -> None:
    deadline = NOW + timedelta(days=14)
    assert _classify(deadline_at=deadline) == FreshnessBucket.open_near


def test_deadline_just_past_the_near_boundary_is_open_far() -> None:
    deadline = NOW + timedelta(days=14, seconds=1)
    assert _classify(deadline_at=deadline) == FreshnessBucket.open_far


def test_expected_to_reopen_this_month_is_upcoming_near() -> None:
    assert (
        _classify(
            public_status=PublicStatus.expected_to_reopen, expected_reopen_month=NOW.month
        )
        == FreshnessBucket.upcoming_near
    )


def test_expected_to_reopen_within_the_far_window_is_upcoming_far() -> None:
    # NOW is June (month 6); August is exactly 2 months out - the far
    # window's own boundary (cfg.upcoming_far_months=2).
    assert (
        _classify(public_status=PublicStatus.expected_to_reopen, expected_reopen_month=8)
        == FreshnessBucket.upcoming_far
    )


def test_expected_to_reopen_outside_the_far_window_is_expected_or_unknown() -> None:
    # December is 6 months out from June - well past the 2-month far window.
    assert (
        _classify(public_status=PublicStatus.expected_to_reopen, expected_reopen_month=12)
        == FreshnessBucket.expected_or_unknown
    )


def test_expected_to_reopen_with_no_month_is_expected_or_unknown() -> None:
    assert (
        _classify(public_status=PublicStatus.expected_to_reopen, expected_reopen_month=None)
        == FreshnessBucket.expected_or_unknown
    )


def test_status_unknown_is_expected_or_unknown() -> None:
    assert (
        _classify(public_status=PublicStatus.status_unknown) == FreshnessBucket.expected_or_unknown
    )


def test_fetch_interval_and_max_evidence_age_read_the_right_bucket() -> None:
    assert fetch_interval(FreshnessBucket.open_near, CFG) == timedelta(hours=6)
    assert max_evidence_age(FreshnessBucket.open_near, CFG) == timedelta(hours=12)
    assert fetch_interval(FreshnessBucket.closed_archive, CFG) == timedelta(hours=2160)
    assert max_evidence_age(FreshnessBucket.rolling_open, CFG) == timedelta(hours=48)


def test_is_reverify_due_when_never_verified() -> None:
    assert is_reverify_due(FreshnessBucket.open_far, last_verified_at=None, now=NOW, cfg=CFG)


def test_is_reverify_due_within_the_interval_is_false() -> None:
    last_verified = NOW - timedelta(hours=1)
    assert not is_reverify_due(
        FreshnessBucket.open_far, last_verified_at=last_verified, now=NOW, cfg=CFG
    )


def test_is_reverify_due_exactly_at_the_interval_boundary_is_true() -> None:
    last_verified = NOW - timedelta(hours=24)
    assert is_reverify_due(
        FreshnessBucket.open_far, last_verified_at=last_verified, now=NOW, cfg=CFG
    )


def test_unchanged_recheck_requires_a_previous_hash() -> None:
    assert not is_unchanged_recheck(
        previous_hash=None, new_hash="abc", http_status=200, status_still_valid=True
    )


def test_unchanged_recheck_requires_a_successful_fetch() -> None:
    assert not is_unchanged_recheck(
        previous_hash="abc", new_hash="abc", http_status=404, status_still_valid=True
    )


def test_unchanged_recheck_requires_a_matching_hash() -> None:
    assert not is_unchanged_recheck(
        previous_hash="abc", new_hash="xyz", http_status=200, status_still_valid=True
    )


def test_unchanged_recheck_requires_status_rules_to_still_pass() -> None:
    assert not is_unchanged_recheck(
        previous_hash="abc", new_hash="abc", http_status=200, status_still_valid=False
    )


def test_unchanged_recheck_true_when_everything_matches() -> None:
    assert is_unchanged_recheck(
        previous_hash="abc", new_hash="abc", http_status=200, status_still_valid=True
    )
