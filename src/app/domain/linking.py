from dataclasses import dataclass
from enum import StrEnum


class LinkOutcome(StrEnum):
    linked = "linked"
    new_candidate = "new_candidate"
    needs_review = "needs_review"


@dataclass(frozen=True)
class LinkDecision:
    outcome: LinkOutcome
    scholarship_id: str | None
    reason: str


def decide_link(candidate_ids: list[str]) -> LinkDecision:
    if len(candidate_ids) == 1:
        return LinkDecision(LinkOutcome.linked, candidate_ids[0], "single_identity_candidate")
    if len(candidate_ids) == 0:
        return LinkDecision(LinkOutcome.new_candidate, None, "no_identity_candidate")
    return LinkDecision(LinkOutcome.needs_review, None, "ambiguous_identity_candidates")
