"""run_sanity_checks - deterministic, no DB, no AI call."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domain.sanity_checks import run_sanity_checks

NOW = datetime(2027, 1, 1, tzinfo=UTC)


def test_a_real_positive_amount_and_no_deadline_passes() -> None:
    result = run_sanity_checks(
        extracted_facts={"funding_mentions": ["£13,000"]}, deadline_at=None, now=NOW
    )
    assert result.has_positive_amount is True
    assert result.deadline_is_future_or_absent is True
    assert result.passed is True


def test_no_amount_at_all_fails() -> None:
    result = run_sanity_checks(extracted_facts={"funding_mentions": []}, deadline_at=None, now=NOW)
    assert result.has_positive_amount is False
    assert result.passed is False


def test_an_unparseable_amount_fails() -> None:
    result = run_sanity_checks(
        extracted_facts={"funding_mentions": ["a generous grant"]}, deadline_at=None, now=NOW
    )
    assert result.has_positive_amount is False


def test_a_future_deadline_passes() -> None:
    result = run_sanity_checks(
        extracted_facts={"funding_mentions": ["£13,000"]},
        deadline_at=NOW + timedelta(days=30),
        now=NOW,
    )
    assert result.deadline_is_future_or_absent is True
    assert result.passed is True


def test_a_lapsed_deadline_fails() -> None:
    result = run_sanity_checks(
        extracted_facts={"funding_mentions": ["£13,000"]},
        deadline_at=NOW - timedelta(days=1),
        now=NOW,
    )
    assert result.deadline_is_future_or_absent is False
    assert result.passed is False


def test_missing_extracted_facts_never_raises() -> None:
    result = run_sanity_checks(extracted_facts=None, deadline_at=None, now=NOW)
    assert result.has_positive_amount is False
