"""Mapping Parse.bot's raw shapes into feed-import fields - no network, no SDK."""

from __future__ import annotations

from datetime import UTC, datetime

from app.domain.parsebot_harvest import opportunity_to_record, scholarship_to_record

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
