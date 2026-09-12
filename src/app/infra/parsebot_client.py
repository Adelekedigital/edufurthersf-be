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

from parse_apis.careeronestop_org_api import CareerOneStop, LevelOfStudy
from parse_apis.fastweb_com_api import Fastweb, Major
from parse_apis.mastersportal_com_api import Mastersportal
from parse_apis.opportunitydesk_org_api import OpportunityDesk
from parse_apis.phdscanner_com_api import Funded, PhDScanner
from parse_apis.scholarshipportal_com_api import ScholarshipPortal

#: Deliberately conservative: enough of a weekly sample to surface new
#: candidates without spending the free-tier credit budget on exhaustive
#: pagination. See docs/parsebot-harvest.md for the credit-cost math.
RESULTS_PER_CALL = 20

#: Opportunity Desk's application_url (the roundup-vs-real-grant filter,
#: see domain/parsebot_harvest.py) only exists on the per-grant detail
#: object, not the list summary - so this source costs 1 + limit calls per
#: run, not 1. Kept smaller than RESULTS_PER_CALL for that reason.
OPPORTUNITY_DESK_RESULTS_PER_CALL = 10

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


def _mastersportal_to_dict(scholarship) -> dict:
    return {
        "title": scholarship.title,
        "url": scholarship.url,
        "deadline": scholarship.deadline,
        "description": scholarship.description,
        "provider_name": scholarship.provider_name,
        "grant_amount": scholarship.grant_amount,
        "grant_currency": scholarship.grant_currency,
        "grant_description": scholarship.grant_description,
    }


def fetch_mastersportal(destination_iso: str, *, limit: int = RESULTS_PER_CALL) -> list[dict]:
    """One destination's scholarships. `destination_country` takes the same
    ISO 2-letter code as our own destination codes (confirmed against
    Mastersportal's own example.py: 'CA', 'GB')."""
    client = Mastersportal()
    return [
        _mastersportal_to_dict(scholarship)
        for scholarship in client.scholarships.search(
            destination_country=destination_iso, limit=limit
        )
    ]


def _opportunitydesk_grant_to_dict(grant) -> dict:
    return {
        "title": grant.title,
        "application_url": grant.application_url,
        "deadline": grant.deadline,
        "eligible_countries": grant.eligible_countries,
        "grant_amount": grant.grant_amount,
    }


def fetch_opportunitydesk(*, limit: int = OPPORTUNITY_DESK_RESULTS_PER_CALL) -> list[dict]:
    """No destination or country filter exists on this API at all - a single
    capped pull of the current grant feed. `application_url` (the
    roundup-vs-real-grant filter - see domain/parsebot_harvest.py) only
    exists on the per-grant detail object, so this costs one `.details()`
    call per summary, not just the initial list call."""
    client = OpportunityDesk()
    summaries = list(client.grant_summaries.list(limit=limit))
    return [_opportunitydesk_grant_to_dict(summary.details()) for summary in summaries]


def _fastweb_to_dict(scholarship) -> dict:
    return {
        "title": scholarship.title,
        "detail_url": scholarship.detail_url,
        "provider": scholarship.provider,
        "award": scholarship.award,
        "deadline": scholarship.deadline,
    }


def fetch_fastweb_featured(*, limit: int = RESULTS_PER_CALL) -> list[dict]:
    """Currently featured/promoted scholarships - no filter axis, US-only
    by nature (Fastweb has no non-US content)."""
    client = Fastweb()
    return [
        _fastweb_to_dict(scholarship) for scholarship in client.scholarships.featured(limit=limit)
    ]


def fetch_fastweb_by_major(major: Major, *, limit: int = RESULTS_PER_CALL) -> list[dict]:
    """One academic major's directory listing - the only other breadth axis
    this API exposes beyond `featured`."""
    client = Fastweb()
    return [
        _fastweb_to_dict(scholarship)
        for scholarship in client.scholarships.by_major(major=major, limit=limit)
    ]


def _careeronestop_to_dict(summary) -> dict:
    return {
        "name": summary.name,
        "url": summary.url,
        "organization": summary.organization,
        "purpose": summary.purpose,
        "award_amount": summary.award_amount,
        "deadline": summary.deadline,
    }


def fetch_careeronestop(*, limit: int = RESULTS_PER_CALL) -> list[dict]:
    """Graduate-level awards only - no destination filter (US-only by
    nature); the catalog is large enough that a plain graduate-level pull,
    capped by `limit`, is a representative weekly sample without needing a
    keyword axis to loop over."""
    client = CareerOneStop()
    return [
        _careeronestop_to_dict(summary)
        for summary in client.scholarship_summaries.search(
            level_of_study=LevelOfStudy.GRADUATE, limit=limit
        )
    ]
