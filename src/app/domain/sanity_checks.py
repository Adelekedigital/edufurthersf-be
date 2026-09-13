"""Deterministic sanity checks over a candidate about to be auto-approved.

Destination/level/award_type membership is already enforced for free by
`build_cycle_facts`/`TAXONOMY.award_type()` (both raise `ValueError` on an
unrecognised code) - duplicating that here would just be the same check
twice. What isn't checked anywhere else: whether there is a real positive
funding figure at all (a proxy for "this is a specific, real award," not
malformed or vague noise), and whether a stated deadline has actually
already passed - nothing in the publish path today rejects a lapsed date.

A real cross-source corroboration can substitute for a stated figure: many
real scholarships are described qualitatively ("fully funded," "course fees
and living costs") with no structured number at all, so requiring one
unconditionally would filter out genuinely well-corroborated matches for
having nothing to state, not for disagreeing. This is never a free pass for
a single thin claim - it only applies when nothing is stated on either side
*and* the identity is independently corroborated by enough real sources.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.domain.fact_matching import parse_amount


@dataclass(frozen=True)
class SanityCheckResult:
    #: A real, parseable, positive currency figure was found - unchanged
    #: meaning, kept for auditability even when it isn't what let this pass.
    has_positive_amount: bool
    #: True when `has_positive_amount` is True, or no amount is stated
    #: anywhere but the identity is corroborated by enough independent
    #: sources to substitute for one. This, not `has_positive_amount`
    #: directly, is what `passed` checks.
    amount_evidence_sufficient: bool
    #: True when there is no deadline to check at all - absence is not a
    #: failure, only a stated-and-already-lapsed date is.
    deadline_is_future_or_absent: bool

    @property
    def passed(self) -> bool:
        return self.amount_evidence_sufficient and self.deadline_is_future_or_absent


def run_sanity_checks(
    *,
    extracted_facts: dict[str, Any] | None,
    deadline_at: datetime | None,
    independent_source_count: int,
    min_corroboration_sources: int,
    now: datetime | None = None,
) -> SanityCheckResult:
    amounts = (extracted_facts or {}).get("funding_mentions") or []
    has_positive_amount = any(
        (parsed := parse_amount(raw)) is not None and parsed[1] > 0 for raw in amounts
    )
    amount_evidence_sufficient = has_positive_amount or (
        not amounts and independent_source_count >= min_corroboration_sources
    )
    current_time = now or datetime.now(UTC)
    deadline_ok = deadline_at is None or deadline_at > current_time
    return SanityCheckResult(
        has_positive_amount=has_positive_amount,
        amount_evidence_sufficient=amount_evidence_sufficient,
        deadline_is_future_or_absent=deadline_ok,
    )
