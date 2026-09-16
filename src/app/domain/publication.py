"""Validating one application cycle's facts before they can be published.

Mirrors the vocabulary search itself validates against: a published record can
only assert destinations, levels and fields the matcher recognises, so a typo
or an unsupported code is refused here rather than silently matching nothing
or everything at read time.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain.countries import CountryVocabulary
from app.domain.taxonomy import TAXONOMY


def build_cycle_facts(
    *,
    destinations: list[str],
    levels: list[str],
    origin_mode: str,
    origins: list[str],
    field_mode: str,
    fields: list[str],
    evidence_fresh: bool,
    deadline_at: datetime | None,
    deadline_precision: Literal["date", "datetime"] = "date",
    deadline_timezone: str | None = None,
    eligibility_note: str | None = None,
    expected_reopen_month: int | None = None,
    field_names: list[str] | None = None,
    programme_names: list[str] | None = None,
    funding_type: str | None = None,
    countries: CountryVocabulary,
) -> dict[str, Any]:
    """Return the validated, normalised `facts` JSONB for a ScholarshipCycle.

    A date-only deadline is never given an invented time of day: the data
    standard's rule is "store date, time, timezone and precision separately,"
    so `deadline_precision`/`deadline_timezone` are stored alongside
    `deadline_at` rather than folded into a single guessed instant.
    Defaulting `deadline_precision` to "date" matches how most real provider
    deadlines are actually stated - a calendar date, not a time of day.

    `eligibility_note` exists for a real restriction `origin_mode` cannot
    represent - an exclude-one rule ("not UK nationals"), an immigration or
    residency status rather than citizenship, an external classification not
    yet enumerated. It is never a substitute for `origin_mode`/`origins` when
    those can honestly capture the restriction; it is what is left when they
    cannot, so the restriction is still visible rather than silently dropped.

    `field_names` is accepted as a legacy input name for source/programme
    wording. It is preserved separately in `programme_names`; canonical field
    labels are generated from `fields`.

    `funding_type` is how much of the cost is covered - distinct from
    `award_types` (what kind of instrument this is). Optional, same honesty
    rule as `eligibility_note`/`expected_reopen_month`: only set it when the
    reviewer has real evidence of coverage, never a default guess.
    """
    normalized_destinations = sorted({countries.destination(value) for value in destinations})
    if not normalized_destinations:
        raise ValueError("At least one destination is required")

    normalized_levels = sorted({TAXONOMY.degree(value) for value in levels})
    if not normalized_levels:
        raise ValueError("At least one degree level is required")

    normalized_origins = sorted({countries.origin(value) for value in origins})
    if origin_mode == "restricted" and not normalized_origins:
        raise ValueError("origin_mode 'restricted' requires at least one origin")

    normalized_fields = sorted({TAXONOMY.field(value) for value in fields})
    if field_mode == "restricted" and not normalized_fields:
        raise ValueError("field_mode 'restricted' requires at least one field")

    if deadline_timezone is not None:
        try:
            ZoneInfo(deadline_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown deadline_timezone {deadline_timezone!r}") from exc

    facts: dict[str, Any] = {
        "destinations": normalized_destinations,
        "levels": normalized_levels,
        "origin_mode": origin_mode,
        "origins": normalized_origins,
        "field_mode": field_mode,
        "fields": normalized_fields,
        "evidence_fresh": evidence_fresh,
    }
    if eligibility_note:
        facts["eligibility_note"] = eligibility_note
    if expected_reopen_month is not None:
        facts["expected_reopen_month"] = expected_reopen_month
    if normalized_fields:
        facts["field_names"] = [TAXONOMY.fields[value] for value in normalized_fields]
    programme_name_source = programme_names if programme_names is not None else field_names or []
    normalized_programme_names = sorted(
        {name.strip() for name in programme_name_source if name.strip()}
    )
    if normalized_programme_names:
        facts["programme_names"] = normalized_programme_names
    if funding_type:
        facts["funding_type"] = TAXONOMY.funding_type(funding_type)
    if deadline_at is not None:
        facts["deadline_at"] = deadline_at.isoformat()
        facts["deadline_precision"] = deadline_precision
        if deadline_timezone is not None:
            facts["deadline_timezone"] = deadline_timezone
    return facts


def cycle_facts_to_inputs(facts: Mapping[str, Any]) -> dict[str, Any]:
    """Read a stored `facts` blob back into the inputs `build_cycle_facts` takes.

    Editing one published cycle has to re-validate the whole of it, not just
    the part that changed: `origin_mode`/`origins` and `field_mode`/`fields`
    constrain each other, so a change to either is only valid against the
    current value of the other. Reconstructing the inputs and re-running the
    same builder keeps one validation path for publishing and editing, rather
    than a second, weaker one that could let an edit write facts a publish
    would have refused.

    `field_names` is deliberately not reconstructed: it is derived from
    `fields` on the way in, so returning it would feed a generated value back
    as if a reviewer had supplied it.
    """
    deadline_at = facts.get("deadline_at")
    parsed_deadline: datetime | None = None
    if isinstance(deadline_at, str) and deadline_at:
        try:
            parsed_deadline = datetime.fromisoformat(deadline_at)
        except ValueError:
            # A blob written before this shape settled, or by hand. Dropping
            # the deadline silently would quietly widen a cycle's window, so
            # refuse and let the caller surface it.
            raise ValueError(
                f"Stored deadline_at {deadline_at!r} is not a valid timestamp"
            ) from None

    def string_list(key: str) -> list[str]:
        value = facts.get(key)
        return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []

    return {
        "destinations": string_list("destinations"),
        "levels": string_list("levels"),
        "origin_mode": facts.get("origin_mode", "unknown"),
        "origins": string_list("origins"),
        "field_mode": facts.get("field_mode", "unknown"),
        "fields": string_list("fields"),
        "evidence_fresh": bool(facts.get("evidence_fresh", False)),
        "deadline_at": parsed_deadline,
        "deadline_precision": facts.get("deadline_precision", "date"),
        "deadline_timezone": facts.get("deadline_timezone"),
        "eligibility_note": facts.get("eligibility_note"),
        "expected_reopen_month": facts.get("expected_reopen_month"),
        "programme_names": string_list("programme_names"),
        "funding_type": facts.get("funding_type"),
    }
