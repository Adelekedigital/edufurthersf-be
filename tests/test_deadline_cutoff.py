"""The data standard's §7 rule: store date, time, timezone and precision
separately; never manufacture midnight or a countdown from an unknown
timezone. `deadline_cutoff` is the fail-closed implementation of that rule."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.models import PublicStatus
from app.domain.status import deadline_cutoff, evaluate_public_status


def test_datetime_precision_is_a_passthrough() -> None:
    instant = datetime(2026, 6, 30, 15, 0, tzinfo=UTC)
    assert deadline_cutoff(instant, precision="datetime", timezone=None) == instant


def test_datetime_precision_assumes_utc_for_a_naive_value() -> None:
    naive = datetime(2026, 6, 30, 15, 0)
    cutoff = deadline_cutoff(naive, precision="datetime", timezone=None)
    assert cutoff == datetime(2026, 6, 30, 15, 0, tzinfo=UTC)


def test_datetime_precision_with_a_naive_value_and_known_timezone_localizes_to_it() -> None:
    """"5pm BST" must convert as BST (UTC+1), not be silently read as "5pm UTC"."""
    naive = datetime(2027, 4, 15, 17, 0)
    cutoff = deadline_cutoff(naive, precision="datetime", timezone="Europe/London")
    assert cutoff == datetime(2027, 4, 15, 16, 0, tzinfo=UTC)


def test_datetime_precision_with_a_naive_value_and_unrecognised_timezone_assumes_utc() -> None:
    naive = datetime(2027, 4, 15, 17, 0)
    cutoff = deadline_cutoff(naive, precision="datetime", timezone="Not/AZone")
    assert cutoff == datetime(2027, 4, 15, 17, 0, tzinfo=UTC)


def test_date_precision_with_a_known_timezone_uses_that_zones_end_of_day() -> None:
    # Any time-of-day on the input is irrelevant once precision is "date" -
    # only the calendar date and the given zone matter.
    given = datetime(2026, 6, 30, 3, 0)
    cutoff = deadline_cutoff(given, precision="date", timezone="America/New_York")
    # 23:59:59 EDT on 2026-06-30 is 2026-07-01 03:59:59 UTC.
    assert cutoff == datetime(2026, 7, 1, 3, 59, 59, tzinfo=UTC)


def test_date_precision_with_an_unrecognised_timezone_falls_back_to_fail_closed() -> None:
    given = datetime(2026, 6, 30, 0, 0)
    cutoff = deadline_cutoff(given, precision="date", timezone="Not/AZone")
    assert cutoff == deadline_cutoff(given, precision="date", timezone=None)


def test_date_precision_with_unknown_timezone_fails_closed_to_utc14() -> None:
    """UTC+14 is the earliest place on Earth a calendar date ends - the
    conservative choice, because the failure mode this prevents is claiming
    "Open now" past a deadline that has, somewhere, already passed."""
    given = datetime(2026, 6, 30, 0, 0)
    cutoff = deadline_cutoff(given, precision="date", timezone=None)
    # 23:59:59 at UTC+14 on 2026-06-30 is 2026-06-30 09:59:59 UTC.
    assert cutoff == datetime(2026, 6, 30, 9, 59, 59, tzinfo=UTC)


def test_unknown_timezone_cutoff_is_earlier_than_the_latest_possible_zone() -> None:
    """The fail-closed cutoff must never be as late as the last place on
    Earth (UTC-12) to finish that date - that would risk still claiming
    "Open now" long after the deadline has passed almost everywhere."""
    given = datetime(2026, 6, 30, 0, 0)
    fail_closed = deadline_cutoff(given, precision="date", timezone=None)
    latest_possible = datetime(2026, 7, 1, 11, 59, 59, tzinfo=UTC)  # UTC-12 end of day
    assert fail_closed < latest_possible


@pytest.mark.parametrize(
    ("hours_after_utc14_cutoff", "expected"),
    [(-1, PublicStatus.open_verified), (1, PublicStatus.status_unknown)],
)
def test_evaluate_public_status_uses_the_fail_closed_cutoff_for_date_precision(
    hours_after_utc14_cutoff: int, expected: PublicStatus
) -> None:
    utc14_cutoff = datetime(2026, 6, 30, 9, 59, 59, tzinfo=UTC)
    now = utc14_cutoff + timedelta(hours=hours_after_utc14_cutoff)
    status = evaluate_public_status(
        PublicStatus.open_verified,
        deadline_at=datetime(2026, 6, 30, 0, 0),
        deadline_precision="date",
        deadline_timezone=None,
        status_valid_until=None,
        now=now,
    )
    assert status == expected


def test_default_precision_preserves_pre_existing_behaviour() -> None:
    """A cycle published before precision/timezone existed on this schema has
    neither key in its stored facts; reading it back must compare deadline_at
    literally, exactly as it always did, not silently start applying the
    date-only fail-closed rule to data that was never described that way."""
    deadline = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
    status = evaluate_public_status(
        PublicStatus.open_verified,
        deadline_at=deadline,
        status_valid_until=None,
        now=deadline + timedelta(seconds=1),
    )
    assert status == PublicStatus.status_unknown
