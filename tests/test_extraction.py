"""Deterministic structured-fact extraction from a discovery's raw text.

Every assertion here is a literal substring match, never an inference: the
whole point of this module is that it explains what the text says without
deciding anything a reviewer should decide instead."""

from __future__ import annotations

from app.domain.extraction import extract_candidate_facts


def test_extraction_is_always_marked_as_needing_human_review() -> None:
    facts = extract_candidate_facts("Some Award", "Some excerpt")
    assert facts["needs_human_review"] is True
    assert facts["extraction_version"]


def test_a_currency_amount_is_extracted() -> None:
    facts = extract_candidate_facts(
        "UCL Mathematics Scholarship", "offers a £13,000 grant towards tuition fees"
    )
    assert facts["funding_mentions"] == ["£13,000"]


def test_a_month_name_deadline_is_extracted() -> None:
    facts = extract_candidate_facts(None, "Applications close on March 15, 2026 at 5pm.")
    assert facts["deadline_mentions"] == ["March 15, 2026"]


def test_degree_level_keywords_are_detected() -> None:
    facts = extract_candidate_facts("PhD Scholarship", "for incoming Master's students")
    assert facts["level_mentions"] == ["doctorate", "masters"]


def test_an_eligibility_phrase_is_captured_verbatim() -> None:
    facts = extract_candidate_facts(
        None, "offering scholarship awards to incoming students from all countries worldwide"
    )
    assert facts["eligibility_phrase"] == "all countries"


def test_absent_signals_are_reported_as_none_or_empty_not_guessed() -> None:
    facts = extract_candidate_facts("Untitled", "")
    assert facts["funding_mentions"] == []
    assert facts["deadline_mentions"] == []
    assert facts["level_mentions"] == []
    assert facts["eligibility_phrase"] is None


def test_missing_title_and_excerpt_do_not_raise() -> None:
    facts = extract_candidate_facts(None, None)
    assert facts["funding_mentions"] == []
