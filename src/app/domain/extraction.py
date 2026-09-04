"""Deterministic structured-fact extraction from a discovery's raw text.

Per the automation boundary: this explains what the text says - a funding
figure, a stated deadline, an eligibility phrase - it never decides whether a
candidate is real, eligible, or publishable. Every extraction is heuristic and
provisional, which is why the result always carries `needs_human_review=True`
rather than anything resembling a verdict.
"""

from __future__ import annotations

import re
from typing import Any

EXTRACTION_VERSION = "extract-v1"

_CURRENCY_AMOUNT = re.compile(r"[£$€]\s?[\d][\d,]*(?:\.\d+)?")
_MONTH_NAME_DATE = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|"
    r"December)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}\b",
    re.IGNORECASE,
)
_LEVEL_KEYWORDS = {
    "doctorate": ("phd", "doctoral", "doctorate"),
    "masters": ("master's", "masters", "msc", "ma ", "mba"),
    "bachelors": ("bachelor's", "bachelors", "undergraduate", "bsc"),
}
_ELIGIBILITY_PHRASES = (
    "all countries",
    "all nationalities",
    "international students",
    "citizens of",
    "residents of",
    "open to",
)


def extract_candidate_facts(raw_title: str | None, raw_excerpt: str | None) -> dict[str, Any]:
    """Pull whatever a reviewer would otherwise have to read prose to find.

    Every field is either a literal substring match or None - nothing here
    infers, normalizes against the taxonomy, or resolves ambiguity. That is
    the reviewer's job, using this as a head start rather than a verdict.
    """
    text = " ".join(part for part in (raw_title, raw_excerpt) if part)
    lowered = text.lower()

    funding_mentions = _CURRENCY_AMOUNT.findall(text)
    deadline_mentions = _MONTH_NAME_DATE.findall(text)

    levels = sorted(
        level
        for level, keywords in _LEVEL_KEYWORDS.items()
        if any(keyword in lowered for keyword in keywords)
    )

    eligibility_snippet = next(
        (phrase for phrase in _ELIGIBILITY_PHRASES if phrase in lowered), None
    )

    return {
        "extraction_version": EXTRACTION_VERSION,
        "needs_human_review": True,
        "funding_mentions": funding_mentions,
        "deadline_mentions": deadline_mentions,
        "level_mentions": levels,
        "eligibility_phrase": eligibility_snippet,
    }
