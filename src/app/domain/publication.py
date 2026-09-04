"""Validating one application cycle's facts before they can be published.

Mirrors the vocabulary search itself validates against: a published record can
only assert destinations, levels and fields the matcher recognises, so a typo
or an unsupported code is refused here rather than silently matching nothing
or everything at read time.
"""

from __future__ import annotations

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
    if deadline_at is not None:
        facts["deadline_at"] = deadline_at.isoformat()
        facts["deadline_precision"] = deadline_precision
        if deadline_timezone is not None:
            facts["deadline_timezone"] = deadline_timezone
    return facts
