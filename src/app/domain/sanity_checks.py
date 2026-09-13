"""Deterministic sanity checks over a candidate about to be auto-approved.

Destination/level/award_type membership is already enforced for free by
`build_cycle_facts`/`TAXONOMY.award_type()` (both raise `ValueError` on an
unrecognised code) - duplicating that here would just be the same check
twice. What isn't checked anywhere else: whether there is a real positive
funding figure at all (a proxy for "this is a specific, real award," not
malformed or vague noise), and whether a stated deadline has actually
already passed - nothing in the publish path today rejects a lapsed date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.domain.fact_matching import parse_amount


@dataclass(frozen=True)
class SanityCheckResult:
    has_positive_amount: bool
    #: True when there is no deadline to check at all - absence is not a
    #: failure, only a stated-and-already-lapsed date is.
    deadline_is_future_or_absent: bool

    @property
    def passed(self) -> bool:
        return self.has_positive_amount and self.deadline_is_future_or_absent


def run_sanity_checks(
    *,
    extracted_facts: dict[str, Any] | None,
    deadline_at: datetime | None,
    now: datetime | None = None,
) -> SanityCheckResult:
    amounts = (extracted_facts or {}).get("funding_mentions") or []
    has_positive_amount = any(
        (parsed := parse_amount(raw)) is not None and parsed[1] > 0 for raw in amounts
    )
    current_time = now or datetime.now(UTC)
    deadline_ok = deadline_at is None or deadline_at > current_time
    return SanityCheckResult(
        has_positive_amount=has_positive_amount, deadline_is_future_or_absent=deadline_ok
    )
