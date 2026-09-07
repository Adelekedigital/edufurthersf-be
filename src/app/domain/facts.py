"""One sanitization pass over a cycle's `facts` JSONB.

Relocated out of `api/routes.py` verbatim (no behavior change) so the
freshness jobs (`infra/freshness.py`) can read `deadline_at`/
`expected_reopen_month`/etc the same sanitized way the public API does,
without `infra/`/`domain/` importing from `api/` - the top of this
project's layering, not something lower layers may depend on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from app.domain.taxonomy import TAXONOMY


def string_list(value: Any) -> list[str]:
    """A facts JSONB list field isn't guaranteed to actually be a list - a
    bare `for x in value` over a non-list raises TypeError, and a non-string
    item fails `list[str]` validation building the response. Silently drops
    anything that isn't a string rather than crash over one bad item."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def safe_deadline_at(value: Any) -> datetime | None:
    """`facts["deadline_at"]` isn't guaranteed to be a valid ISO string once
    a row can be written outside `publish()` - a bare `fromisoformat` call
    raises ValueError/TypeError on anything else."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class DerivedFacts:
    deadline_at: datetime | None
    #: Never null - a value the contract can't represent (missing, or out of
    #: {"date","datetime"}) clamps to "datetime", the same fallback already
    #: used when the key is simply absent, so this feeds `evaluate_public_status`/
    #: `evaluate_status_detail` identically regardless of what the public
    #: field ends up showing. Use `.public_deadline_precision` for the
    #: response field itself - null whenever there's no deadline at all.
    deadline_precision: Literal["date", "datetime"]
    deadline_timezone: str | None
    degree_levels: list[str]
    expected_reopen_month: int | None
    funding_type: str | None
    destinations: list[str]
    eligibility_note: str | None
    field_names: list[str]
    origin_mode: Literal["restricted", "unrestricted", "unknown"]
    origins: list[str]
    field_mode: Literal["restricted", "all", "unknown"]
    fields: list[str]
    evidence_fresh: bool

    @property
    def public_deadline_precision(self) -> Literal["date", "datetime"] | None:
        return self.deadline_precision if self.deadline_at else None

    @property
    def sanitized_dict(self) -> dict[str, Any]:
        """The same key shape `build_cycle_facts` writes, rebuilt from these
        sanitized values rather than passed through from the raw stored
        dict - so `ScholarshipDetailResponse.facts` can never disagree with
        this same dataclass's own typed response fields the way the raw
        dict could (e.g. a garbled `deadline_precision` clamped to
        "datetime" in the typed field but still showing the garbage value
        verbatim in `facts`)."""
        result: dict[str, Any] = {
            "destinations": self.destinations,
            "levels": self.degree_levels,
            "origin_mode": self.origin_mode,
            "origins": self.origins,
            "field_mode": self.field_mode,
            "fields": self.fields,
            "evidence_fresh": self.evidence_fresh,
        }
        if self.eligibility_note is not None:
            result["eligibility_note"] = self.eligibility_note
        if self.expected_reopen_month is not None:
            result["expected_reopen_month"] = self.expected_reopen_month
        if self.field_names:
            result["field_names"] = self.field_names
        if self.funding_type is not None:
            result["funding_type"] = self.funding_type
        if self.deadline_at is not None:
            result["deadline_at"] = self.deadline_at.isoformat()
            result["deadline_precision"] = self.deadline_precision
            if self.deadline_timezone is not None:
                result["deadline_timezone"] = self.deadline_timezone
        return result


def derive_facts(facts: dict) -> DerivedFacts:
    """One sanitization pass over a cycle's `facts` JSONB, shared by
    `_search_result`, `_detail` and the freshness jobs.

    `facts` isn't schema-enforced below `publish()` - a row written directly
    by one of this repo's own one-off admin/backfill scripts could hold a
    value outside contract for any of these. Three failure modes that matter
    here: an unguarded value can crash the whole response building a
    strictly-typed SearchResult/ScholarshipDetailResponse field (a non-ISO
    deadline_at, a non-Literal deadline_precision, a non-list `levels`/
    `field_names` or one with non-string items, a non-string
    eligibility_note); `raw_value in TAXONOMY.funding_types` raises
    TypeError instead of returning False if `raw_value` is unhashable (a
    list or dict), so an isinstance check has to come first; and, subtler,
    computing status/status_detail from the *raw* value while only
    sanitizing what's shown to the caller produces an internally
    contradictory response (status_detail: "opening_soon" next to a nulled
    expected_reopen_month). Deriving everything once, upfront, and feeding
    the same sanitized values to both the status computation and the public
    fields closes all three at once.
    """
    deadline_at = safe_deadline_at(facts.get("deadline_at"))
    raw_precision = facts.get("deadline_precision", "datetime")
    deadline_precision: Literal["date", "datetime"] = (
        raw_precision if raw_precision in ("date", "datetime") else "datetime"
    )
    raw_reopen_month = facts.get("expected_reopen_month")
    expected_reopen_month = (
        raw_reopen_month
        if isinstance(raw_reopen_month, int)
        and not isinstance(raw_reopen_month, bool)
        and 1 <= raw_reopen_month <= 12
        else None
    )
    raw_funding_type = facts.get("funding_type")
    funding_type = None
    if isinstance(raw_funding_type, str):
        try:
            # Reuse the same validator publish() uses (strip/lower included)
            # rather than a second, separately-maintained membership check
            # that could drift out of sync with what publish-time accepts.
            funding_type = TAXONOMY.funding_type(raw_funding_type)
        except ValueError:
            funding_type = None
    raw_destinations = facts.get("destinations", [])
    destinations = (
        sorted({str(value) for value in raw_destinations})
        if isinstance(raw_destinations, list)
        else []
    )
    raw_eligibility_note = facts.get("eligibility_note")
    # Truthy, not just isinstance(str) - build_cycle_facts only ever writes
    # this key for a non-empty note (matching eligibility_note's own
    # honesty rule: an empty string means nothing was provided, same as
    # absent). A bare isinstance check would let "" through and disagree
    # with the shape build_cycle_facts can actually produce.
    eligibility_note = (
        raw_eligibility_note
        if isinstance(raw_eligibility_note, str) and raw_eligibility_note
        else None
    )
    raw_deadline_timezone = facts.get("deadline_timezone")
    deadline_timezone = raw_deadline_timezone if isinstance(raw_deadline_timezone, str) else None
    raw_origin_mode = facts.get("origin_mode")
    origin_mode: Literal["restricted", "unrestricted", "unknown"] = (
        raw_origin_mode
        if raw_origin_mode in ("restricted", "unrestricted", "unknown")
        else "unknown"
    )
    raw_field_mode = facts.get("field_mode")
    field_mode: Literal["restricted", "all", "unknown"] = (
        raw_field_mode if raw_field_mode in ("restricted", "all", "unknown") else "unknown"
    )
    raw_evidence_fresh = facts.get("evidence_fresh")
    evidence_fresh = raw_evidence_fresh if isinstance(raw_evidence_fresh, bool) else False
    return DerivedFacts(
        deadline_at=deadline_at,
        deadline_precision=deadline_precision,
        deadline_timezone=deadline_timezone,
        degree_levels=string_list(facts.get("levels", [])),
        expected_reopen_month=expected_reopen_month,
        funding_type=funding_type,
        destinations=destinations,
        eligibility_note=eligibility_note,
        field_names=string_list(facts.get("field_names", [])),
        origin_mode=origin_mode,
        origins=string_list(facts.get("origins", [])),
        field_mode=field_mode,
        fields=string_list(facts.get("fields", [])),
        evidence_fresh=evidence_fresh,
    )
