import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain.models import PublicStatus

#: UTC+14 is the first timezone anywhere to finish a given calendar date.
#: Used as the fail-closed cutoff for a date-only deadline whose provider
#: timezone is unknown - see `deadline_cutoff`.
_FAIL_CLOSED_TZ = dt.timezone(dt.timedelta(hours=14))


def deadline_cutoff(
    deadline_at: dt.datetime, *, precision: str, timezone: str | None
) -> dt.datetime:
    """The UTC instant after which a deadline is treated as passed.

    An official date-only deadline is never given an invented time of day or a
    countdown. When the provider's timezone is known, the cutoff is that
    timezone's own end of day. When it is not, the cutoff is the earliest
    place on Earth (UTC+14) where that calendar date ends - not the latest
    (UTC-12) - because the failure this exists to prevent is claiming "Open
    now" past a deadline that has, somewhere, already passed. This is a
    display fail-safe, not a claim about when the provider's deadline actually
    falls.

    `precision="datetime"` means the caller already holds a real instant - an
    exact date and time. If it already carries a UTC offset, this is a no-op
    passthrough. A naive value paired with a known `timezone` is localized to
    that zone rather than assumed UTC, so a stated "5pm BST" is not silently
    read as "5pm UTC." Only a naive value with no known zone falls back to
    assuming UTC, to avoid raising when compared against an aware `now`.
    """
    if precision != "date":
        if deadline_at.tzinfo:
            return deadline_at
        if timezone:
            try:
                return deadline_at.replace(tzinfo=ZoneInfo(timezone)).astimezone(dt.UTC)
            except ZoneInfoNotFoundError:
                pass
        return deadline_at.replace(tzinfo=dt.UTC)
    zone: dt.tzinfo = _FAIL_CLOSED_TZ
    if timezone:
        try:
            zone = ZoneInfo(timezone)
        except ZoneInfoNotFoundError:
            zone = _FAIL_CLOSED_TZ
    end_of_day = dt.datetime.combine(deadline_at.date(), dt.time(23, 59, 59), tzinfo=zone)
    return end_of_day.astimezone(dt.UTC)


def evaluate_public_status(
    stored_status: PublicStatus,
    *,
    deadline_at: dt.datetime | None,
    status_valid_until: dt.datetime | None,
    deadline_precision: str = "datetime",
    deadline_timezone: str | None = None,
    now: dt.datetime | None = None,
) -> PublicStatus:
    """Re-evaluate time-sensitive status on read; never keep an expired Open now result.

    `deadline_precision` defaults to "datetime" - the literal instant is used
    as-is - so a cycle published before precision/timezone existed on this
    schema keeps exactly the comparison it always had. A reviewer publishing a
    date-only deadline should pass `precision="date"` explicitly to get the
    fail-closed end-of-day handling `deadline_cutoff` implements.
    """
    current = now or dt.datetime.now(dt.UTC)
    if stored_status == PublicStatus.open_verified:
        if deadline_at:
            cutoff = deadline_cutoff(
                deadline_at, precision=deadline_precision, timezone=deadline_timezone
            )
            if cutoff <= current:
                return PublicStatus.status_unknown
        if status_valid_until and status_valid_until <= current:
            return PublicStatus.status_unknown
    return stored_status


#: A deadline this close is "closing soon," not just generically open -
#: chosen as a round, defensible lead time; not derived from any evidence
#: standard, so revisit if it doesn't match how searchers actually behave.
CLOSING_SOON_WINDOW_DAYS = 14


def evaluate_status_detail(
    status: PublicStatus,
    *,
    deadline_at: dt.datetime | None,
    deadline_precision: str = "datetime",
    deadline_timezone: str | None = None,
    expected_reopen_month: int | None,
    now: dt.datetime | None = None,
) -> str:
    """A display-only refinement of `status`, never a replacement for it.

    `status` (open_verified/expected_to_reopen/status_unknown) stays the
    authoritative business state everything else - matching, confirmed
    counts, re-verification caveats - is computed from. This only adds the
    granularity a searcher actually wants to see: "open" vs. "closing soon"
    for a live deadline, and "likely to reopen" vs. "opening soon" for a
    recurring scheme, when a reviewer has actually captured evidence of
    roughly when (`expected_reopen_month`). Call with the *already
    re-evaluated* `status` (from `evaluate_public_status`), not the raw
    stored value, so a lapsed "open_verified" is never shown as "closing
    soon" after it has, in fact, already closed.
    """
    current = now or dt.datetime.now(dt.UTC)
    if status == PublicStatus.open_verified:
        if deadline_at:
            cutoff = deadline_cutoff(
                deadline_at, precision=deadline_precision, timezone=deadline_timezone
            )
            if cutoff - current <= dt.timedelta(days=CLOSING_SOON_WINDOW_DAYS):
                return "closing_soon"
        return "open"
    if status == PublicStatus.expected_to_reopen:
        if expected_reopen_month is not None:
            # 0 = reopens this month, 1 = reopens next month - anything
            # further out is "likely to reopen" without a near-term signal.
            months_until_reopen = (expected_reopen_month - current.month) % 12
            if months_until_reopen <= 1:
                return "opening_soon"
        return "likely_to_reopen"
    return "status_unknown"
