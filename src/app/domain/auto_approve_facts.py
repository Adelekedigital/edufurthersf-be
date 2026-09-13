"""Turn provisional extracted facts into the structured shape
`build_cycle_facts` requires - failing closed on any ambiguity, per the
verification standard's "no taxonomy-forcing" bar.

`field_mode`/`origin_mode` are deliberately never resolved here - always
left "unknown" by the caller. Confidently mapping free text to a specific
restriction (an exclude-one rule, an immigration status, a demographic
condition - the standard names three distinct shapes none of which map onto
a single field) or a specific canonical field code is exactly the kind of
judgement call this module must not make unsupervised; asserting less than
what a human might eventually confirm is the safe failure direction, never
asserting something untrue.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any

from app.domain.fact_matching import parse_deadline
from app.domain.review_draft import mentioned_countries
from app.domain.taxonomy import TAXONOMY

#: Coarse, deliberately conservative phrase map - only ever narrows toward
#: `None` (the schema already allows funding_type to be left unset), never
#: guessed from an amount alone (a given figure could be full or partial
#: funding depending on real costs this text does not state).
_FUNDING_TYPE_PHRASES: dict[str, str] = {
    "fully funded": "fully_funded",
    "fully-funded": "fully_funded",
    "full funding": "fully_funded",
    "tuition waiver": "tuition_only",
    "tuition only": "tuition_only",
    "tuition-only": "tuition_only",
    "stipend only": "stipend_only",
    "stipend-only": "stipend_only",
    "partial funding": "partial_funding",
    "partial scholarship": "partial_funding",
}


@dataclass(frozen=True)
class DerivedCycleFacts:
    destinations: list[str]
    levels: list[str]
    award_type: str
    funding_type: str | None
    deadline_at: datetime | None


def derive_cycle_facts_from_extraction(
    *,
    raw_title: str | None,
    raw_excerpt: str | None,
    page_text: str,
    extracted_facts: dict[str, Any] | None,
    country_names: dict[str, str],
) -> DerivedCycleFacts | None:
    combined_text = " ".join(part for part in (raw_title, raw_excerpt, page_text) if part)

    supported, other = mentioned_countries(combined_text, country_names)
    if len(supported) != 1 or other:
        # Anything but exactly one supported destination named, with nothing
        # else in scope, is ambiguous about which country actually hosts the
        # study - the same closure prepare_review's own destination screen
        # already applies, just requiring more certainty for auto-approve
        # than it does for a plain "not obviously out of scope" ambiguous draft.
        return None

    facts = extracted_facts or {}
    canonical_levels, _unmapped = TAXONOMY.normalize_degrees(facts.get("level_mentions") or [])
    if not canonical_levels:
        return None

    award_type = _resolve_agreed_award_type(raw_title, raw_excerpt, page_text)
    if award_type is None:
        return None

    return DerivedCycleFacts(
        destinations=[supported[0]],
        levels=canonical_levels,
        award_type=award_type,
        funding_type=_resolve_funding_type(page_text.lower()),
        deadline_at=_resolve_deadline(facts.get("deadline_mentions") or []),
    )


def _resolve_agreed_award_type(
    raw_title: str | None, raw_excerpt: str | None, page_text: str
) -> str | None:
    """Only resolves when the aggregator's own text and the real page agree
    on the same explicit word - never inferred from context, since a wrong
    award_type misrepresents what kind of instrument this actually is."""
    aggregator_text = " ".join(part for part in (raw_title, raw_excerpt) if part).lower()
    page_lower = page_text.lower()
    for keyword in TAXONOMY.award_types:
        pattern = rf"\b{re.escape(keyword)}\b"
        if re.search(pattern, aggregator_text) and re.search(pattern, page_lower):
            return keyword
    return None


def _resolve_funding_type(page_lower: str) -> str | None:
    for phrase, canonical in _FUNDING_TYPE_PHRASES.items():
        if phrase in page_lower:
            return canonical
    return None


def _resolve_deadline(deadline_mentions: list[str]) -> datetime | None:
    for raw in deadline_mentions:
        parsed = parse_deadline(raw)
        if parsed is not None:
            return datetime.combine(parsed, time.min, tzinfo=UTC)
    return None
