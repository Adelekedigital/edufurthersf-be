"""I/O boundary for Parse.bot's marketplace APIs.

The only module that imports `parse_apis` - keeps the generated SDK's types
out of the domain layer entirely. Each function fetches one destination's
results and hands back plain dicts for `domain/parsebot_harvest.py` to map,
never the SDK's own resource objects.

Reads `PARSE_API_KEY` from the process environment itself (the SDK's own
convention - see `parse_apis/CLAUDE.md`), not through `app.core.config`.
"""

from __future__ import annotations

from typing import Literal

from parse_apis.phdscanner_com_api import Funded, PhDScanner
from parse_apis.scholarshipportal_com_api import ScholarshipPortal

#: Deliberately conservative: enough of a weekly sample to surface new
#: candidates without spending the free-tier credit budget on exhaustive
#: pagination. See docs/parsebot-harvest.md for the credit-cost math.
RESULTS_PER_CALL = 20

_PHDSCANNER_COUNTRY_NAMES = {
    "CA": "Canada",
    "GB": "United Kingdom",
    "US": "United States",
    "DE": "Germany",
    "FI": "Finland",
}


def _scholarship_to_dict(scholarship) -> dict:
    provider = getattr(scholarship, "provider", None)
    return {
        "title": scholarship.title,
        "url": scholarship.url,
        "benefits": scholarship.benefits,
        "deadline": scholarship.deadline,
        "provider": {"name": provider.name} if provider is not None else None,
    }


def _opportunity_to_dict(opportunity) -> dict:
    return {
        "title": opportunity.title,
        "opportunity_url": opportunity.opportunity_url,
        "university": opportunity.university,
        "department": opportunity.department,
        "category": opportunity.category,
        "created_at": opportunity.created_at,
    }


def fetch_scholarshipportal(
    destination_iso: str,
    study_level: Literal["phd", "master", "bachelor"],
    *,
    limit: int = RESULTS_PER_CALL,
) -> list[dict]:
    """One destination, one degree level ('master' or 'phd')."""
    portal = ScholarshipPortal()
    return [
        _scholarship_to_dict(scholarship)
        for scholarship in portal.scholarships.search(
            country_iso=destination_iso, study_level=study_level, limit=limit
        )
    ]


def fetch_phdscanner(destination_iso: str, *, limit: int = RESULTS_PER_CALL) -> list[dict]:
    """One destination's funded PhD opportunities. No country filter beyond
    the plain English country name PhDScanner itself expects."""
    country_name = _PHDSCANNER_COUNTRY_NAMES.get(destination_iso)
    if country_name is None:
        return []
    client = PhDScanner()
    return [
        _opportunity_to_dict(opportunity)
        for opportunity in client.opportunities.search(
            country=country_name, funded=Funded.TRUE, limit=limit
        )
    ]
