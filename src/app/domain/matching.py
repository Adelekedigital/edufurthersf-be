from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SearchProfile:
    origin_country: str
    target_countries: frozenset[str]
    program_level: str
    field: str


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
    if field_mode == "restricted" and _normalise(profile.field) not in fields:
        return None
    possible = origin_mode == "unknown" or field_mode == "unknown"
    score = 0
    reasons: list[str] = []
    if field_mode == "all" or _normalise(profile.field) in fields:
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
