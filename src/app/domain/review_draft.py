"""Draft a review recommendation - never decide, never publish.

Per the automation boundary ("AI may extract structured candidate facts and
explain deterministic matches... must not independently verify, decide
eligibility, or publish scholarships"), this only ever writes a *proposal* a
human reviewer confirms or edits - it never touches ReviewTask.state.

One thing it can draft with real confidence, because it is the same fast,
objective closure already applied by hand at scale this session (125 of the
first 247 discoveries): an institution's country is a stable fact from its
own name, not an evidence-quality judgement call. A destination clearly
outside the five supported ones is drafted as `reject`. Everything else is
drafted `ambiguous` - never `confident_pass` - because confirming a candidate
requires fetching and reading the real official source
(docs/candidate-verification-standard.md), which this heuristic cannot do.
"""

from __future__ import annotations

import re
from typing import Any

from app.domain.countries import SUPPORTED_DESTINATIONS

DRAFT_VERSION = "prepare_review-v1"


def _mentioned_countries(text: str, country_names: dict[str, str]) -> tuple[list[str], list[str]]:
    """Country codes named in `text`, split into supported vs. other.

    Matched against the mirrored country vocabulary, never a hand-typed list,
    per the standard's own country-list-resolution rule. A whole-word match:
    "Niger" must not fire on "Nigeria".
    """
    supported: set[str] = set()
    other: set[str] = set()
    for code, display_name in country_names.items():
        if not display_name:
            continue
        if re.search(rf"\b{re.escape(display_name)}\b", text, re.IGNORECASE):
            (supported if code in SUPPORTED_DESTINATIONS else other).add(code)
    return sorted(supported), sorted(other)


def draft_review_recommendation(
    *,
    raw_title: str | None,
    raw_excerpt: str | None,
    extracted_facts: dict[str, Any] | None,
    country_names: dict[str, str],
) -> dict[str, Any]:
    """Build the draft attached to ReviewTask.draft_recommendation.

    `extracted_facts` is carried through as `proposed_facts` verbatim - it is
    already a reviewer head start (see domain/extraction.py), not something
    this step re-derives. `proposed_award_type` is always None: nothing short
    of reading the real official page can honestly say what an award actually
    is, and a wrong guess here is exactly the kind of taxonomy-forcing the
    standard prohibits.
    """
    text = " ".join(part for part in (raw_title, raw_excerpt) if part)
    supported, other = _mentioned_countries(text, country_names)

    if other and not supported:
        named = ", ".join(country_names[code] for code in other)
        reasoning = [
            f"Destination screen: text names {named}, none of the five supported "
            f"destinations ({', '.join(sorted(SUPPORTED_DESTINATIONS))}).",
            "Fast, objective closure - an institution's country is knowable from its "
            "own name, not an evidence-quality call - but this is a text match, not "
            "a verified fact: confirm the named country actually is the institution's "
            "before acting on this draft, since a name collision (a US state, a "
            "surname, a partial match) is possible.",
        ]
        verdict = "reject"
    else:
        if supported:
            note = f"a supported destination is also named ({', '.join(supported)})"
        elif other:
            note = "an out-of-scope country is named alongside a supported one"
        else:
            note = "no country name was found in the text"
        reasoning = [
            f"Destination screen did not find a clear out-of-scope closure ({note}).",
            "No automated fetch-and-cross-check has run: full verification against "
            "the real official source still requires a human pass per "
            "docs/candidate-verification-standard.md.",
        ]
        verdict = "ambiguous"

    return {
        "draft_version": DRAFT_VERSION,
        "verdict": verdict,
        "reasoning": reasoning,
        "proposed_award_type": None,
        "proposed_facts": extracted_facts or {},
    }
