"""Mapping Parse.bot's raw shapes into feed-import fields - no network, no SDK."""

from __future__ import annotations

from datetime import UTC, datetime

from app.domain.parsebot_harvest import (
    careeronestop_to_record,
    fastweb_to_record,
    mastersportal_to_record,
    opportunity_to_record,
    opportunitydesk_to_record,
    scholarship_to_record,
)

HARVESTED_AT = datetime(2026, 9, 5, tzinfo=UTC)


def test_scholarship_maps_title_url_and_excerpt() -> None:
    record = scholarship_to_record(
        {
            "title": "Chevening Scholarships",
            "url": "https://www.scholarshipportal.com/scholarships/chevening",
            "benefits": "Various benefits",
            "deadline": "Not specified",
            "provider": {"name": "UK Government"},
        },
        harvested_at=HARVESTED_AT,
    )
    assert record is not None
    assert record.title == "Chevening Scholarships"
    assert record.url == "https://www.scholarshipportal.com/scholarships/chevening"
    assert "UK Government" in record.excerpt
    assert "Various benefits" in record.excerpt
    # A discovery signal only - never harvested_at except as a fallback for
    # PhDScanner. ScholarshipPortal has no per-item timestamp of its own.
    assert record.feed_created_at == HARVESTED_AT


def test_scholarship_without_title_or_url_is_dropped() -> None:
    assert (
        scholarship_to_record({"title": "", "url": "https://x.example"}, harvested_at=HARVESTED_AT)
        is None
    )
    assert scholarship_to_record({"title": "X", "url": ""}, harvested_at=HARVESTED_AT) is None


def test_scholarship_never_reads_deadline_into_a_date_field() -> None:
    """The deadline may appear in the excerpt as free text (informational),
    but must never populate feed_created_at/source_posted_at - only a human
    reviewer asserts a deadline, at publish time, from the real page."""
    record = scholarship_to_record(
        {"title": "X", "url": "https://x.example", "deadline": "23 Jan 2027"},
        harvested_at=HARVESTED_AT,
    )
    assert record is not None
    assert record.feed_created_at == HARVESTED_AT


def test_opportunity_maps_and_uses_its_own_created_at() -> None:
    record = opportunity_to_record(
        {
            "title": "Fully Funded PhD Studentship in Foundational AI",
            "opportunity_url": "https://phdscanner.com/opportunities/abc123",
            "university": "University College London",
            "department": "Electronic and Electrical Engineering",
            "category": "AI",
            "created_at": 1767225600,  # 2026-01-01T00:00:00Z
        },
        harvested_at=HARVESTED_AT,
    )
    assert record is not None
    assert record.url == "https://phdscanner.com/opportunities/abc123"
    assert "University College London" in record.excerpt
    assert record.feed_created_at == datetime(2026, 1, 1, tzinfo=UTC)


def test_opportunity_falls_back_to_harvested_at_without_created_at() -> None:
    record = opportunity_to_record(
        {"title": "X", "opportunity_url": "https://phdscanner.com/x", "created_at": None},
        harvested_at=HARVESTED_AT,
    )
    assert record is not None
    assert record.feed_created_at == HARVESTED_AT


def test_opportunity_without_title_or_url_is_dropped() -> None:
    assert (
        opportunity_to_record(
            {"title": "", "opportunity_url": "https://x"}, harvested_at=HARVESTED_AT
        )
        is None
    )
    assert (
        opportunity_to_record({"title": "X", "opportunity_url": ""}, harvested_at=HARVESTED_AT)
        is None
    )


def test_mastersportal_maps_title_url_and_excerpt() -> None:
    record = mastersportal_to_record(
        {
            "title": "Aalto University Master's Scholarship",
            "url": "https://www.mastersportal.com/scholarships/12345",
            "provider_name": "Aalto University",
            "grant_description": "Covers full tuition fee",
            "deadline": "31 Jan 2027",
            "grant_amount": 15000,
            "grant_currency": "EUR",
        },
        harvested_at=HARVESTED_AT,
    )
    assert record is not None
    assert record.title == "Aalto University Master's Scholarship"
    assert "Aalto University" in record.excerpt
    assert "15000 EUR" in record.excerpt
    assert record.feed_created_at == HARVESTED_AT


def test_mastersportal_without_title_or_url_is_dropped() -> None:
    no_title = {"title": "", "url": "https://x.example"}
    assert mastersportal_to_record(no_title, harvested_at=HARVESTED_AT) is None
    no_url = {"title": "X", "url": ""}
    assert mastersportal_to_record(no_url, harvested_at=HARVESTED_AT) is None


def test_opportunitydesk_uses_application_url_as_the_records_url() -> None:
    record = opportunitydesk_to_record(
        {
            "title": "Climate Action Grant for African Youth",
            "application_url": "https://apply.example-foundation.org/climate-grant",
            "eligible_countries": ["Kenya", "Nigeria", "Ghana"],
            "grant_amount": "$5,000",
            "deadline": "15 March 2027",
        },
        harvested_at=HARVESTED_AT,
    )
    assert record is not None
    assert record.url == "https://apply.example-foundation.org/climate-grant"
    assert "Kenya" in record.excerpt


def test_opportunitydesk_without_application_url_is_dropped() -> None:
    """The empirically-found filter (docs/scholarship-source-options.md,
    2026-09-12): every real individual grant sampled had application_url
    set; every aggregate "roundup" post did not. Dropping here, in the
    mapping layer, keeps the client a dumb fetcher and this rule
    unit-testable without mocking the SDK."""
    record = opportunitydesk_to_record(
        {
            "title": "10 Grants for African Startups You Should Know About",
            "application_url": None,
            "eligible_countries": ["Kenya", "Nigeria", "Ghana", "Uganda", "Tanzania"],
        },
        harvested_at=HARVESTED_AT,
    )
    assert record is None


def test_fastweb_maps_title_url_and_excerpt() -> None:
    record = fastweb_to_record(
        {
            "title": "Women's League Scholarship",
            "detail_url": "https://www.fastweb.com/scholarships/77822",
            "provider": "American Legion Auxiliary",
            "award": "$1,000",
            "deadline": "1 April 2027",
        },
        harvested_at=HARVESTED_AT,
    )
    assert record is not None
    assert "American Legion Auxiliary" in record.excerpt
    assert "$1,000" in record.excerpt


def test_fastweb_without_title_or_url_is_dropped() -> None:
    no_title = {"title": "", "detail_url": "https://x.example"}
    assert fastweb_to_record(no_title, harvested_at=HARVESTED_AT) is None
    no_url = {"title": "X", "detail_url": ""}
    assert fastweb_to_record(no_url, harvested_at=HARVESTED_AT) is None


def test_careeronestop_maps_title_url_and_excerpt() -> None:
    record = careeronestop_to_record(
        {
            "name": "AAUW International Fellowship",
            "url": "https://www.careeronestop.org/scholarships/54321",
            "organization": "American Association of University Women",
            "purpose": "Graduate study for women",
            "award_amount": "$20,000-$50,000",
            "deadline": "1 December",
        },
        harvested_at=HARVESTED_AT,
    )
    assert record is not None
    assert record.title == "AAUW International Fellowship"
    assert "American Association of University Women" in record.excerpt


def test_careeronestop_without_name_or_url_is_dropped() -> None:
    assert (
        careeronestop_to_record({"name": "", "url": "https://x.example"}, harvested_at=HARVESTED_AT)
        is None
    )
    assert careeronestop_to_record({"name": "X", "url": ""}, harvested_at=HARVESTED_AT) is None
