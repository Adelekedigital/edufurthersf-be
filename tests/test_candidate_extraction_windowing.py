"""_window_page_text - cuts a real fetched page to size around whatever
looks like a funding figure or a deadline, rather than a blind head
truncation."""

from __future__ import annotations

from app.infra.candidate_extraction import _window_page_text


def test_no_matches_falls_back_to_a_head_truncation() -> None:
    text = "no money or dates mentioned anywhere on this long page. " * 50
    windowed = _window_page_text(text, max_bytes=100)
    assert windowed == text.encode()[:100].decode(errors="ignore")


def test_a_match_keeps_its_surrounding_context() -> None:
    padding = "irrelevant filler text. " * 40
    text = f"{padding}Awards a £13,000 grant to successful applicants.{padding}"
    windowed = _window_page_text(text, max_bytes=16 * 1024)
    assert "£13,000" in windowed
    assert "Awards a £13,000 grant" in windowed


def test_overlapping_windows_around_nearby_matches_are_merged_not_duplicated() -> None:
    text = "The award is £13,000, deadline March 1, 2027, open to all applicants."
    windowed = _window_page_text(text, max_bytes=16 * 1024)
    # Both matches sit inside one merged window - the whole sentence appears
    # exactly once, not duplicated by two separate windows.
    assert windowed.count("£13,000") == 1
    assert windowed.count("March 1, 2027") == 1


def test_result_never_exceeds_the_byte_cap() -> None:
    text = ("Awards a £13,000 grant. " * 2000) + "deadline March 1, 2027."
    windowed = _window_page_text(text, max_bytes=500)
    assert len(windowed.encode()) <= 500
