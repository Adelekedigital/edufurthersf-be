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


def test_amounts_match_is_unknown_when_either_side_is_unparseable() -> None:
    """Not agreement - but not disagreement either.

    This asserted False, which reads as "these differ". Callers use the
    result inside `any(...)`, so both are falsy and corroboration is
    unaffected; the distinction matters because the Edufurther Agent reads
    the same comparators to decide REJECT_RECOMMENDED, where False asserts
    that an official page contradicts a claim. It rejected a real award on
    a value it had simply failed to parse.
    """
    assert amounts_match("£13,000", "a generous grant") is None
    assert amounts_match("a generous grant", "£13,000") is None


def test_parse_deadline_handles_ordinal_suffix_and_optional_comma() -> None:
    from datetime import date

    assert parse_deadline("March 15, 2026") == date(2026, 3, 15)
    assert parse_deadline("March 15th 2026") == date(2026, 3, 15)


def test_parse_deadline_rejects_unparseable_text() -> None:
    assert parse_deadline("sometime next spring") is None


def test_deadlines_match_requires_the_same_calendar_date() -> None:
    assert deadlines_match("March 15, 2026", "March 15th, 2026") is True
    assert deadlines_match("March 15, 2026", "March 16, 2026") is False


def test_deadlines_match_is_unknown_when_either_side_is_unparseable() -> None:
    """Same distinction as amounts."""
    assert deadlines_match("March 15, 2026", "soon") is None
    assert deadlines_match("soon", "March 15, 2026") is None


# --- how real pages write money and dates -------------------------------


def test_an_iso_currency_code_is_read() -> None:
    """Official pages overwhelmingly write "992 EUR", not "€992". Reading
    symbols only meant a deadline or an amount stated plainly in the text
    produced no mention at all."""
    assert amounts_match("EUR 992", "€992") is True
    assert amounts_match("GBP 10,000", "£10,000") is True
    assert amounts_match("992 EUR", "EUR 992") is True


def test_a_date_written_day_first_is_read() -> None:
    """`deadlines_match("15 March 2026", "15 March 2026")` returned False -
    two identical strings called a contradiction, because only
    "March 15 2026" ever parsed."""
    assert deadlines_match("15 March 2026", "March 15, 2026") is True
    assert deadlines_match("15 March 2026", "2026-03-15") is True


def test_the_standards_worst_near_miss_still_fails() -> None:
    """UCL claimed £13,000 against a real £16,750. Widening what can be
    read must not widen what counts as agreement."""
    assert amounts_match("£13,000", "£16,750") is False
    assert amounts_match("GBP 13,000", "GBP 16,750") is False


def test_a_different_currency_is_still_not_agreement() -> None:
    assert amounts_match("EUR 10,000", "USD 10,000") is False
    assert amounts_match("GBP 10,000", "$10,000") is False
