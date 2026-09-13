"""Does another independent source report the same award with matching facts?

Pure and deterministic, same style as `review_priority.py` - never an AI
judgement, always auditable. `normalized_identity_key` matching (the caller's
job, see `infra/corroboration.py`) only proves two discoveries *name* the same
award; this module is what checks whether they *agree* on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.domain.fact_matching import amounts_match, deadlines_match

#: (discovery_id, source_id, extracted_facts) for one discovery sharing the
#: subject discovery's `normalized_identity_key`, excluding itself.
SiblingFact = tuple[UUID, UUID, "dict[str, Any] | None"]


@dataclass(frozen=True)
class CorroborationResult:
    #: Distinct sources (including the subject's own) reporting this identity.
    independent_source_count: int
    amount_corroborated: bool
    #: `None` when the subject discovery itself asserts no deadline - nothing
    #: to corroborate, not a failure. `False` only when it asserts one and no
    #: sibling agrees.
    deadline_corroborated: bool | None
    corroborating_discovery_ids: list[str] = field(default_factory=list)


def evaluate_corroboration(
    *,
    own_source_id: UUID,
    own_facts: dict[str, Any] | None,
    siblings: list[SiblingFact],
) -> CorroborationResult:
    own_amounts = (own_facts or {}).get("funding_mentions") or []
    own_deadlines = (own_facts or {}).get("deadline_mentions") or []

    distinct_sources = {own_source_id}
    corroborating_ids: list[str] = []
    amount_corroborated = False
    deadline_corroborated: bool | None = None if not own_deadlines else False

    for discovery_id, source_id, facts in siblings:
        distinct_sources.add(source_id)
        sibling_amounts = (facts or {}).get("funding_mentions") or []
        sibling_deadlines = (facts or {}).get("deadline_mentions") or []

        matched = False
        if any(amounts_match(a, b) for a in own_amounts for b in sibling_amounts):
            amount_corroborated = True
            matched = True
        if own_deadlines and any(
            deadlines_match(a, b) for a in own_deadlines for b in sibling_deadlines
        ):
            deadline_corroborated = True
            matched = True
        if matched:
            corroborating_ids.append(str(discovery_id))

    return CorroborationResult(
        independent_source_count=len(distinct_sources),
        amount_corroborated=amount_corroborated,
        deadline_corroborated=deadline_corroborated,
        corroborating_discovery_ids=corroborating_ids,
    )
