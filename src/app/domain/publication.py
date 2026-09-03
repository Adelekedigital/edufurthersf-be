"""Validating one application cycle's facts before they can be published.

Mirrors the vocabulary search itself validates against: a published record can
only assert destinations, levels and fields the matcher recognises, so a typo
or an unsupported code is refused here rather than silently matching nothing
or everything at read time.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

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
    countries: CountryVocabulary,
) -> dict[str, Any]:
    """Return the validated, normalised `facts` JSONB for a ScholarshipCycle."""
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

    facts: dict[str, Any] = {
        "destinations": normalized_destinations,
        "levels": normalized_levels,
        "origin_mode": origin_mode,
        "origins": normalized_origins,
        "field_mode": field_mode,
        "fields": normalized_fields,
        "evidence_fresh": evidence_fresh,
    }
    if deadline_at is not None:
        facts["deadline_at"] = deadline_at.isoformat()
    return facts
