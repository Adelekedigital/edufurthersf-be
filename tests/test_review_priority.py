"""compute_review_priority - deterministic, no AI call of its own."""

from __future__ import annotations

from app.domain.review_priority import (
    MIN_PRIORITY,
    NEEDS_REVIEW_BASE,
    NEW_CANDIDATE_BASE,
    compute_review_priority,
)


def test_bare_new_candidate_gets_the_base_score() -> None:
    score = compute_review_priority(
        needs_review=False, extracted_facts=None, ai_extracted_facts=None, authority_grade=None
    )
    assert score == NEW_CANDIDATE_BASE


def test_bare_needs_review_gets_the_base_score() -> None:
    score = compute_review_priority(
        needs_review=True, extracted_facts=None, ai_extracted_facts=None, authority_grade=None
    )
    assert score == NEEDS_REVIEW_BASE


def test_needs_review_outranks_new_candidate_at_equal_completeness() -> None:
    kwargs = {"extracted_facts": None, "ai_extracted_facts": None, "authority_grade": None}
    assert compute_review_priority(needs_review=True, **kwargs) < compute_review_priority(
        needs_review=False, **kwargs
    )


def test_authority_grade_a_or_b_scores_lower_than_c_or_unknown() -> None:
    kwargs = {"needs_review": False, "extracted_facts": None, "ai_extracted_facts": None}
    a_score = compute_review_priority(authority_grade="A", **kwargs)
    b_score = compute_review_priority(authority_grade="B", **kwargs)
    c_score = compute_review_priority(authority_grade="C", **kwargs)
    unknown_score = compute_review_priority(authority_grade=None, **kwargs)
    assert a_score < c_score
    assert b_score < c_score
    assert c_score == unknown_score


def test_populated_extracted_facts_score_lower_than_empty() -> None:
    complete = compute_review_priority(
        needs_review=False,
        extracted_facts={
            "funding_mentions": ["£13,000"],
            "deadline_mentions": ["1 March 2027"],
            "level_mentions": ["masters"],
        },
        ai_extracted_facts=None,
        authority_grade=None,
    )
    empty = compute_review_priority(
        needs_review=False, extracted_facts={}, ai_extracted_facts=None, authority_grade=None
    )
    assert complete < empty


def test_ai_evidence_scores_lower_than_no_ai_output() -> None:
    with_evidence = compute_review_priority(
        needs_review=False,
        extracted_facts=None,
        ai_extracted_facts={"candidate": {"amount": "£1,000"}, "evidence": ["quote"]},
        authority_grade=None,
    )
    without = compute_review_priority(
        needs_review=False,
        extracted_facts=None,
        ai_extracted_facts={"candidate": {}, "evidence": []},
        authority_grade=None,
    )
    no_output_at_all = compute_review_priority(
        needs_review=False, extracted_facts=None, ai_extracted_facts=None, authority_grade=None
    )
    assert with_evidence < without == no_output_at_all


def test_the_most_complete_candidate_never_scores_below_the_floor() -> None:
    score = compute_review_priority(
        needs_review=True,
        extracted_facts={
            "funding_mentions": ["£13,000"],
            "deadline_mentions": ["1 March 2027"],
            "level_mentions": ["masters"],
        },
        ai_extracted_facts={"candidate": {"amount": "£13,000"}, "evidence": ["quote"]},
        authority_grade="A",
    )
    assert score >= MIN_PRIORITY
