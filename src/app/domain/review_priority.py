"""Deterministic review-queue prioritization.

Never AI-generated, always auditable: every input here is already stored on
`Discovery`/`Source`, so a reviewer (or a future debugger) can always see
exactly why a task landed where it did by reading the same fields
themselves - no black box, no separate model call of its own.

Lower priority number surfaces first, matching `review_queue`'s existing
`ORDER BY ReviewTask.priority, ReviewTask.created_at`.
"""

from __future__ import annotations

#: Baselines matching linking.py's existing precedent from before this
#: module existed: an ambiguous link (needs_review - a reviewer must pick
#: among existing candidates) already outranked a brand-new identity
#: (new_candidate) by a flat 50 vs. 100. Preserved as the band each score
#: adjusts within, not replaced.
NEEDS_REVIEW_BASE = 50
NEW_CANDIDATE_BASE = 100

#: Points subtracted per positive signal - small and additive, so no single
#: signal alone can push a low-quality candidate to the very front.
_AUTHORITY_AB_BONUS = 20
_HAS_FUNDING_BONUS = 10
_HAS_DEADLINE_BONUS = 10
_HAS_DEGREE_LEVEL_BONUS = 5
_HAS_AI_EVIDENCE_BONUS = 10

#: `ReviewTask.priority` has no documented negative-value contract
#: elsewhere in this codebase - never let scoring push below this floor.
MIN_PRIORITY = 1


def compute_review_priority(
    *,
    needs_review: bool,
    extracted_facts: dict | None,
    ai_extracted_facts: dict | None,
    authority_grade: str | None,
) -> int:
    """Lower = more urgent/promising, surfaces first in the review queue.

    `needs_review` distinguishes an ambiguous-link task (an existing
    candidate scholarship needs disambiguating) from a brand-new-identity
    task - the two starting bands `linking.py` already used before this
    function existed.
    """
    score = NEEDS_REVIEW_BASE if needs_review else NEW_CANDIDATE_BASE

    if authority_grade in ("A", "B"):
        score -= _AUTHORITY_AB_BONUS

    facts = extracted_facts or {}
    if facts.get("funding_mentions"):
        score -= _HAS_FUNDING_BONUS
    if facts.get("deadline_mentions"):
        score -= _HAS_DEADLINE_BONUS
    if facts.get("level_mentions"):
        score -= _HAS_DEGREE_LEVEL_BONUS

    ai_output = ai_extracted_facts or {}
    evidence = ai_output.get("evidence")
    if isinstance(evidence, list) and evidence:
        score -= _HAS_AI_EVIDENCE_BONUS

    return max(score, MIN_PRIORITY)
