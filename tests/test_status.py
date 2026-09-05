from datetime import UTC, datetime, timedelta

from app.domain.models import PublicStatus
from app.domain.status import evaluate_public_status, evaluate_status_detail

#: A fixed instant (15 Jan) rather than datetime.now() - "opening soon"
#: depends on calendar month arithmetic, which must not be flaky depending on
#: which day this suite happens to run.
JAN_15 = datetime(2026, 1, 15, tzinfo=UTC)


def test_expired_deadline_downgrades_open_status() -> None:
    now = datetime.now(UTC)
    assert (
        evaluate_public_status(
            PublicStatus.open_verified,
            deadline_at=now - timedelta(seconds=1),
            status_valid_until=now + timedelta(days=1),
            now=now,
        )
        == PublicStatus.status_unknown
    )


def test_fresh_open_status_remains_open() -> None:
    now = datetime.now(UTC)
    assert (
        evaluate_public_status(
            PublicStatus.open_verified,
            deadline_at=now + timedelta(days=1),
            status_valid_until=now + timedelta(days=1),
            now=now,
        )
        == PublicStatus.open_verified
    )


def test_open_with_a_distant_deadline_is_just_open() -> None:
    detail = evaluate_status_detail(
        PublicStatus.open_verified,
        deadline_at=JAN_15 + timedelta(days=30),
        expected_reopen_month=None,
        now=JAN_15,
    )
    assert detail == "open"


def test_open_with_a_near_deadline_is_closing_soon() -> None:
    detail = evaluate_status_detail(
        PublicStatus.open_verified,
        deadline_at=JAN_15 + timedelta(days=7),
        expected_reopen_month=None,
        now=JAN_15,
    )
    assert detail == "closing_soon"


def test_open_with_no_deadline_at_all_is_just_open() -> None:
    """No deadline is not "closing soon" by default - there's nothing to be
    close to."""
    detail = evaluate_status_detail(
        PublicStatus.open_verified, deadline_at=None, expected_reopen_month=None, now=JAN_15
    )
    assert detail == "open"


def test_reopens_this_month_is_opening_soon() -> None:
    detail = evaluate_status_detail(
        PublicStatus.expected_to_reopen,
        deadline_at=None,
        expected_reopen_month=1,
        now=JAN_15,
    )
    assert detail == "opening_soon"


def test_reopens_next_month_is_still_opening_soon() -> None:
    detail = evaluate_status_detail(
        PublicStatus.expected_to_reopen,
        deadline_at=None,
        expected_reopen_month=2,
        now=JAN_15,
    )
    assert detail == "opening_soon"


def test_reopens_far_out_is_likely_to_reopen_not_opening_soon() -> None:
    detail = evaluate_status_detail(
        PublicStatus.expected_to_reopen,
        deadline_at=None,
        expected_reopen_month=6,
        now=JAN_15,
    )
    assert detail == "likely_to_reopen"


def test_reopen_month_wraps_the_calendar_year() -> None:
    """December, evaluated in November, is "next month" even though 12 < 11
    - reopen timing must wrap the year boundary, not compare raw month ints."""
    detail = evaluate_status_detail(
        PublicStatus.expected_to_reopen,
        deadline_at=None,
        expected_reopen_month=12,
        now=datetime(2026, 11, 20, tzinfo=UTC),
    )
    assert detail == "opening_soon"


def test_expected_to_reopen_without_any_reopen_evidence_is_likely_to_reopen() -> None:
    """No guessed reopen month - only a real, reviewer-captured one ever
    produces "opening soon"."""
    detail = evaluate_status_detail(
        PublicStatus.expected_to_reopen,
        deadline_at=None,
        expected_reopen_month=None,
        now=JAN_15,
    )
    assert detail == "likely_to_reopen"


def test_status_unknown_has_no_richer_detail() -> None:
    detail = evaluate_status_detail(
        PublicStatus.status_unknown,
        deadline_at=JAN_15 + timedelta(days=1),
        expected_reopen_month=1,
        now=JAN_15,
    )
    assert detail == "status_unknown"
