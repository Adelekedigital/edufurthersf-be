"""A diagnostic score for an auto-approved candidate - stored for later
recalibration once the sampling audit has real accuracy data, never the v1
gate itself (that's a strict boolean AND of the individual checks, computed
in `infra/auto_approval.py`). A starting point to be adjusted with evidence,
not engineered further ahead of that evidence existing.
"""

from __future__ import annotations

_BASE_CORROBORATION_SCORE = 40
_EXTRA_SOURCE_BONUS = 10
_EXTRA_SOURCE_BONUS_CAP = 20
_AMOUNT_AGREEMENT_BONUS = 20
_DEADLINE_AGREEMENT_BONUS = 20
_SANITY_CHECK_BONUS = 10
#: Not a gate (the user's explicit scope decision: any source can qualify,
#: including Tier C) - logged only, so the sampling audit can tell whether
#: Tier C auto-approvals are the ones that later turn out wrong.
_NON_AB_AUTHORITY_PENALTY = 30


def compute_auto_approval_score(
    *,
    independent_source_count: int,
    amount_matches_real_page: bool,
    deadline_matches_real_page: bool | None,
    sanity_passed: bool,
    authority_grade: str | None,
) -> int:
    score = 0
    if independent_source_count >= 2:
        score += _BASE_CORROBORATION_SCORE
        score += min((independent_source_count - 2) * _EXTRA_SOURCE_BONUS, _EXTRA_SOURCE_BONUS_CAP)
    if amount_matches_real_page:
        score += _AMOUNT_AGREEMENT_BONUS
    if deadline_matches_real_page:
        score += _DEADLINE_AGREEMENT_BONUS
    if sanity_passed:
        score += _SANITY_CHECK_BONUS
    if authority_grade not in ("A", "B"):
        score -= _NON_AB_AUTHORITY_PENALTY
    return score
