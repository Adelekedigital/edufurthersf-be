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

#: Shared with `infra/candidate_extraction.py`'s real-page windowing - the
#: same substrings worth extracting here are the ones worth showing the AI
#: Router when a full page (not just a short excerpt) is the input.
#: An explicit list, not `[A-Z]{3}`. Any three capitals beside a number
#: made "ROOM 101" and "THE 2026 handbook" into funding - a false
#: amount is worse than a missing one, because it can then be compared
#: against a real figure and disagree with it.
_CURRENCY_CODES = (
    r"(?:GBP|USD|EUR|CAD|AUD|NZD|CHF|JPY|CNY|INR|ZAR|SEK|NOK|DKK|SGD"
    r"|HKD|NGN|KES|GHS|TRY|BRL|MXN|PLN|CZK|HUF|RON|AED|SAR)"
)
CURRENCY_AMOUNT_PATTERN = re.compile(
    rf"(?:[£$€]\s?[\d][\d,]*(?:\.\d+)?"
    rf"|\b{_CURRENCY_CODES}\s?[\d][\d,]*(?:\.\d+)?"
    rf"|\b[\d][\d,]*(?:\.\d+)?\s?{_CURRENCY_CODES}\b)"
)
#: Month-name dates in either order, plus ISO. Only "March 15 2026"
#: matched before, so "15 March 2026" - how most of the world writes it,
#: and most of the pages we fetch - was not a deadline as far as this
#: was concerned.
_MONTHS = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?"
    r"|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
MONTH_NAME_DATE_PATTERN = re.compile(
    rf"\b(?:{_MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}"
    rf"|\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTHS},?\s+\d{{4}}"
    r"|\d{4}-\d{2}-\d{2})\b",
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

    funding_mentions = CURRENCY_AMOUNT_PATTERN.findall(text)
    deadline_mentions = MONTH_NAME_DATE_PATTERN.findall(text)

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
