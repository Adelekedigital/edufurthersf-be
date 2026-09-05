from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SearchProfile:
    origin_country: str
    target_countries: frozenset[str]
    program_level: str
    #: None means "no field preference" - never excludes a field_mode="restricted"
    #: record, since the searcher isn't filtering on field at all. Otherwise
    #: the set of narrow ISCED-F codes accepted for the searcher's broad
    #: field choice (see `taxonomy.normalize_search_filters`) - a scholarship
    #: matches if any of its own narrow-tagged fields falls in this set.
    fields: frozenset[str] | None


@dataclass(frozen=True)
class MatchDecision:
    fit: str
    score: int
    reason_codes: tuple[str, ...]
    caveats: tuple[str, ...]


def _normalise(value: str) -> str:
    return value.strip().lower()


def evaluate_match(profile: SearchProfile, facts: dict[str, Any]) -> MatchDecision | None:
    """Apply the V1 hard gates and deterministic match-v1 score."""
    destinations = {_normalise(str(v)) for v in facts.get("destinations", [])}
    if not destinations.intersection({_normalise(v) for v in profile.target_countries}):
        return None
    if _normalise(profile.program_level) not in {
        _normalise(str(v)) for v in facts.get("levels", [])
    }:
        return None
    origin_mode = facts.get("origin_mode", "unknown")
    origins = {_normalise(str(v)) for v in facts.get("origins", [])}
    if origin_mode == "restricted" and _normalise(profile.origin_country) not in origins:
        return None
    field_mode = facts.get("field_mode", "unknown")
    fields = {_normalise(str(v)) for v in facts.get("fields", [])}
    accepted_fields = (
        {_normalise(v) for v in profile.fields} if profile.fields is not None else None
    )
    if (
        field_mode == "restricted"
        and accepted_fields is not None
        and fields.isdisjoint(accepted_fields)
    ):
        return None
    possible = origin_mode == "unknown" or field_mode == "unknown"
    score = 0
    reasons: list[str] = []
    field_compatible = accepted_fields is not None and not fields.isdisjoint(accepted_fields)
    if field_mode == "all" or field_compatible:
        score += 25
        reasons.append("field_compatible")
    if origin_mode == "unrestricted" or _normalise(profile.origin_country) in origins:
        score += 15
        reasons.append("origin_eligible")
    if facts.get("evidence_fresh", False):
        score += 10
        reasons.append("fresh_verified_evidence")
    caveats = ("Some eligibility conditions need checking.",) if possible else ()
    return MatchDecision("possible" if possible else "confirmed", score, tuple(reasons), caveats)
