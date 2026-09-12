"""Mapping Tavily's raw search results into feed-import fields - no network."""

from __future__ import annotations

from datetime import UTC, datetime

from app.domain.tavily_harvest import tavily_result_to_record

HARVESTED_AT = datetime(2026, 9, 12, tzinfo=UTC)


def test_result_maps_title_url_and_excerpt() -> None:
    record = tavily_result_to_record(
        {
            "title": "Fully Funded PhD Scholarships in Turkiye",
            "url": "https://www.turkiyeburslari.gov.tr/sayfa/phd-scholarships",
            "content": "Turkiye offers fully funded PhD scholarships covering tuition...",
            "score": 0.87,
        },
        harvested_at=HARVESTED_AT,
    )
    assert record is not None
    assert record.title == "Fully Funded PhD Scholarships in Turkiye"
    assert record.url == "https://www.turkiyeburslari.gov.tr/sayfa/phd-scholarships"
    assert record.excerpt is not None
    assert "fully funded" in record.excerpt
    # No per-item discovery timestamp from Tavily - always this harvest run's time.
    assert record.feed_created_at == HARVESTED_AT


def test_result_without_title_or_url_is_dropped() -> None:
    no_title = {"title": "", "url": "https://x.example"}
    assert tavily_result_to_record(no_title, harvested_at=HARVESTED_AT) is None
    no_url = {"title": "X", "url": ""}
    assert tavily_result_to_record(no_url, harvested_at=HARVESTED_AT) is None


def test_result_without_content_has_no_excerpt() -> None:
    record = tavily_result_to_record(
        {"title": "X", "url": "https://x.example"}, harvested_at=HARVESTED_AT
    )
    assert record is not None
    assert record.excerpt is None
