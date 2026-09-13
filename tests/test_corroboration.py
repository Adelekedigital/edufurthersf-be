"""evaluate_corroboration - pure, deterministic, no DB."""

from __future__ import annotations

from uuid import uuid4

from app.domain.corroboration import evaluate_corroboration

OWN_SOURCE = uuid4()
SIBLING_SOURCE = uuid4()
ANOTHER_SIBLING_SOURCE = uuid4()


def test_no_siblings_gives_a_solo_source_and_no_corroboration() -> None:
    result = evaluate_corroboration(
        own_source_id=OWN_SOURCE,
        own_facts={"funding_mentions": ["£13,000"], "deadline_mentions": []},
        siblings=[],
    )
    assert result.independent_source_count == 1
    assert result.amount_corroborated is False
    assert result.deadline_corroborated is None
    assert result.corroborating_discovery_ids == []


def test_a_sibling_with_a_matching_amount_corroborates_it() -> None:
    sibling_id = uuid4()
    result = evaluate_corroboration(
        own_source_id=OWN_SOURCE,
        own_facts={"funding_mentions": ["£13,000"]},
        siblings=[(sibling_id, SIBLING_SOURCE, {"funding_mentions": ["£13,000"]})],
    )
    assert result.independent_source_count == 2
    assert result.amount_corroborated is True
    assert result.corroborating_discovery_ids == [str(sibling_id)]


def test_a_sibling_with_a_conflicting_amount_does_not_corroborate() -> None:
    result = evaluate_corroboration(
        own_source_id=OWN_SOURCE,
        own_facts={"funding_mentions": ["£13,000"]},
        siblings=[(uuid4(), SIBLING_SOURCE, {"funding_mentions": ["£16,750"]})],
    )
    assert result.amount_corroborated is False
    assert result.corroborating_discovery_ids == []


def test_deadline_corroborated_is_none_when_own_facts_assert_no_deadline() -> None:
    result = evaluate_corroboration(
        own_source_id=OWN_SOURCE,
        own_facts={"funding_mentions": ["£13,000"], "deadline_mentions": []},
        siblings=[(uuid4(), SIBLING_SOURCE, {"deadline_mentions": ["March 15, 2026"]})],
    )
    assert result.deadline_corroborated is None


def test_deadline_corroborated_is_false_when_no_sibling_agrees() -> None:
    result = evaluate_corroboration(
        own_source_id=OWN_SOURCE,
        own_facts={"deadline_mentions": ["March 15, 2026"]},
        siblings=[(uuid4(), SIBLING_SOURCE, {"deadline_mentions": ["April 1, 2026"]})],
    )
    assert result.deadline_corroborated is False


def test_deadline_corroborated_is_true_when_a_sibling_agrees() -> None:
    result = evaluate_corroboration(
        own_source_id=OWN_SOURCE,
        own_facts={"deadline_mentions": ["March 15, 2026"]},
        siblings=[(uuid4(), SIBLING_SOURCE, {"deadline_mentions": ["March 15, 2026"]})],
    )
    assert result.deadline_corroborated is True


def test_two_siblings_from_the_same_source_count_as_one_independent_source() -> None:
    """Two pages from the same aggregator are not independent evidence."""
    result = evaluate_corroboration(
        own_source_id=OWN_SOURCE,
        own_facts={"funding_mentions": ["£13,000"]},
        siblings=[
            (uuid4(), SIBLING_SOURCE, {"funding_mentions": ["£13,000"]}),
            (uuid4(), SIBLING_SOURCE, {"funding_mentions": ["£13,000"]}),
        ],
    )
    assert result.independent_source_count == 2


def test_three_distinct_sources_all_count() -> None:
    result = evaluate_corroboration(
        own_source_id=OWN_SOURCE,
        own_facts={"funding_mentions": ["£13,000"]},
        siblings=[
            (uuid4(), SIBLING_SOURCE, {"funding_mentions": ["£13,000"]}),
            (uuid4(), ANOTHER_SIBLING_SOURCE, {"funding_mentions": ["£13,000"]}),
        ],
    )
    assert result.independent_source_count == 3


def test_missing_facts_never_raise() -> None:
    result = evaluate_corroboration(
        own_source_id=OWN_SOURCE, own_facts=None, siblings=[(uuid4(), SIBLING_SOURCE, None)]
    )
    # Nothing on our own side to corroborate - not applicable, not a failure.
    assert result.amount_corroborated is None


def test_amount_corroborated_is_none_when_own_facts_assert_no_amount() -> None:
    """Many real scholarships are described qualitatively ("fully funded")
    with no structured figure at all - nothing stated is not the same as
    stated-and-disagreed."""
    result = evaluate_corroboration(
        own_source_id=OWN_SOURCE,
        own_facts={"funding_mentions": []},
        siblings=[(uuid4(), SIBLING_SOURCE, {"funding_mentions": ["£13,000"]})],
    )
    assert result.amount_corroborated is None


def test_amount_corroborated_is_false_when_own_states_one_and_no_sibling_agrees() -> None:
    """A real, unchanged case: asserting an amount with nothing to back it up
    still fails - the relaxation only ever applies when nothing is stated."""
    result = evaluate_corroboration(
        own_source_id=OWN_SOURCE,
        own_facts={"funding_mentions": ["£13,000"]},
        siblings=[(uuid4(), SIBLING_SOURCE, {"funding_mentions": []})],
    )
    assert result.amount_corroborated is False
    assert result.deadline_corroborated is None
