"""compute_auto_approval_score - diagnostic only, never the v1 gate."""

from __future__ import annotations

from app.domain.auto_approval_scoring import compute_auto_approval_score


def _score(**overrides) -> int:
    kwargs = {
        "independent_source_count": 2,
        "amount_matches_real_page": True,
        "deadline_matches_real_page": True,
        "sanity_passed": True,
        "authority_grade": "A",
    }
    kwargs.update(overrides)
    return compute_auto_approval_score(**kwargs)


def test_a_fully_corroborated_tier_a_candidate_scores_highest() -> None:
    assert _score() == 40 + 20 + 20 + 10


def test_extra_independent_sources_add_a_capped_bonus() -> None:
    assert _score(independent_source_count=3) == 40 + 10 + 20 + 20 + 10
    # Capped at +20 regardless of how many more sources pile on.
    assert _score(independent_source_count=10) == 40 + 20 + 20 + 20 + 10


def test_below_the_corroboration_floor_scores_no_base_at_all() -> None:
    assert _score(independent_source_count=1) == 20 + 20 + 10


def test_a_non_ab_source_is_penalized_but_never_gates() -> None:
    ab_score = _score(authority_grade="A")
    c_score = _score(authority_grade="C")
    unknown_score = _score(authority_grade=None)
    assert c_score == ab_score - 30
    assert unknown_score == c_score


def test_deadline_agreement_only_adds_when_true_not_none_or_false() -> None:
    assert _score(deadline_matches_real_page=None) == _score(deadline_matches_real_page=False)
    assert _score(deadline_matches_real_page=True) == _score(deadline_matches_real_page=None) + 20
