"""run_sanity_checks - deterministic, no DB, no AI call."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domain.sanity_checks import run_sanity_checks

NOW = datetime(2027, 1, 1, tzinfo=UTC)


def _check(**overrides):
    kwargs = {
        "extracted_facts": {"funding_mentions": ["£13,000"]},
        "deadline_at": None,
        "independent_source_count": 1,
        "min_corroboration_sources": 2,
        "now": NOW,
    }
    kwargs.update(overrides)
    return run_sanity_checks(**kwargs)


def test_a_real_positive_amount_and_no_deadline_passes() -> None:
    result = _check()
    assert result.has_positive_amount is True
    assert result.amount_evidence_sufficient is True
    assert result.deadline_is_future_or_absent is True
    assert result.passed is True


def test_no_amount_and_insufficient_corroboration_fails() -> None:
    result = _check(
        extracted_facts={"funding_mentions": []}, independent_source_count=1
    )
    assert result.has_positive_amount is False
    assert result.amount_evidence_sufficient is False
    assert result.passed is False


def test_no_amount_but_enough_corroborating_sources_passes() -> None:
    """The actual substitute: nothing stated on either side, but real,
    independent cross-source agreement on the identity stands in for a
    figure - never a free pass for a single thin, uncorroborated claim."""
    result = _check(
        extracted_facts={"funding_mentions": []},
        independent_source_count=2,
        min_corroboration_sources=2,
    )
    assert result.has_positive_amount is False
    assert result.amount_evidence_sufficient is True
    assert result.passed is True


def test_a_real_amount_passes_regardless_of_corroboration_count() -> None:
    """Unchanged case: a real stated figure never needed corroboration to
    count - the substitute only matters when nothing is stated at all."""
    result = _check(
        extracted_facts={"funding_mentions": ["£13,000"]}, independent_source_count=1
    )
    assert result.amount_evidence_sufficient is True


def test_an_unparseable_amount_fails() -> None:
    result = _check(
        extracted_facts={"funding_mentions": ["a generous grant"]}, independent_source_count=1
    )
    assert result.has_positive_amount is False
    assert result.amount_evidence_sufficient is False


def test_a_future_deadline_passes() -> None:
    result = _check(deadline_at=NOW + timedelta(days=30))
    assert result.deadline_is_future_or_absent is True
    assert result.passed is True


def test_a_lapsed_deadline_fails() -> None:
    result = _check(deadline_at=NOW - timedelta(days=1))
    assert result.deadline_is_future_or_absent is False
    assert result.passed is False


def test_missing_extracted_facts_never_raises() -> None:
    result = _check(extracted_facts=None, independent_source_count=0)
    assert result.has_positive_amount is False
    assert result.amount_evidence_sufficient is False
