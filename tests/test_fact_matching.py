"""fact_matching - exact-match parsing/comparison, no fuzzy tolerance."""

from __future__ import annotations

from decimal import Decimal

from app.domain.fact_matching import (
    amounts_match,
    deadlines_match,
    parse_amount,
    parse_deadline,
)


def test_parse_amount_reads_currency_and_value() -> None:
    assert parse_amount("£13,000") == ("£", Decimal("13000"))
    assert parse_amount("$1,000.50") == ("$", Decimal("1000.50"))


def test_parse_amount_rejects_unparseable_text() -> None:
    assert parse_amount("thirteen thousand pounds") is None
    assert parse_amount("") is None


def test_amounts_match_requires_same_currency_and_value() -> None:
    assert amounts_match("£13,000", "£13,000") is True
    assert amounts_match("£13,000", "£13,000.00") is True


def test_amounts_match_rejects_a_near_miss() -> None:
    """The UCL failure this whole standard was built around: £13,000 claimed
    vs. £16,750 real - a close number must never count as agreement."""
    assert amounts_match("£13,000", "£16,750") is False


def test_amounts_match_rejects_different_currency() -> None:
    assert amounts_match("£13,000", "$13,000") is False


def test_amounts_match_false_when_either_side_is_unparseable() -> None:
    assert amounts_match("£13,000", "a generous grant") is False


def test_parse_deadline_handles_ordinal_suffix_and_optional_comma() -> None:
    from datetime import date

    assert parse_deadline("March 15, 2026") == date(2026, 3, 15)
    assert parse_deadline("March 15th 2026") == date(2026, 3, 15)


def test_parse_deadline_rejects_unparseable_text() -> None:
    assert parse_deadline("sometime next spring") is None


def test_deadlines_match_requires_the_same_calendar_date() -> None:
    assert deadlines_match("March 15, 2026", "March 15th, 2026") is True
    assert deadlines_match("March 15, 2026", "March 16, 2026") is False


def test_deadlines_match_false_when_either_side_is_unparseable() -> None:
    assert deadlines_match("March 15, 2026", "soon") is False
