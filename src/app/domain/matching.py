from dataclasses import dataclass
from typing import Any

from app.domain.taxonomy import TAXONOMY


@dataclass(frozen=True)
class SearchProfile:
    origin_country: str
    target_countries: frozenset[str]
    program_levels: frozenset[str]
    #: None means "no field preference"; otherwise canonical product fields.
    fields: frozenset[str] | None


@dataclass(frozen=True)
class MatchDecision:
    fit: str
    score: int
    reason_codes: tuple[str, ...]
    caveats: tuple[str, ...]


def _normalise(value: str) -> str:
    return value.strip().lower()


def _normalised_set(facts: dict[str, Any], key: str) -> set[str]:
    """`facts.get(key, [])` only substitutes the default when the key is
    absent, not when it's present but explicitly null (or anything else
    that isn't a list) - facts isn't schema-enforced below `publish()`, and
    a bare `for v in facts.get(key, [])` over `None` raises TypeError here,
    in the per-row hard-gate loop every /search request runs - a single
    corrupted row would 500 the whole response, not just fail to match."""
    value = facts.get(key)
    if not isinstance(value, list):
        return set()
    if key in {"fields", "levels"}:
        normalized: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                continue
            try:
                normalized.add(TAXONOMY.field(item) if key == "fields" else TAXONOMY.degree(item))
            except ValueError:
                continue
        return normalized
    return {_normalise(str(v)) for v in value}


def evaluate_match(profile: SearchProfile, facts: dict[str, Any]) -> MatchDecision | None:
    """Apply the hard gates and deterministic score for the policy version
    recorded as `MATCH_POLICY_VERSION` in `api/routes.py` - bump that
    constant whenever this function's gating/scoring semantics change."""
    destinations = _normalised_set(facts, "destinations")
    if not destinations.intersection({_normalise(v) for v in profile.target_countries}):
        return None
    if not {_normalise(v) for v in profile.program_levels}.intersection(
        _normalised_set(facts, "levels")
    ):
        return None
    origin_mode = facts.get("origin_mode") or "unknown"
    origins = _normalised_set(facts, "origins")
    if origin_mode == "restricted" and _normalise(profile.origin_country) not in origins:
        return None
    field_mode = facts.get("field_mode") or "unknown"
    fields = _normalised_set(facts, "fields")
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
