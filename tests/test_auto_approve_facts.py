"""derive_cycle_facts_from_extraction - fails closed on any ambiguity."""

from __future__ import annotations

from datetime import UTC, datetime

from app.domain.auto_approve_facts import derive_cycle_facts_from_extraction

COUNTRY_NAMES = {"GB": "United Kingdom", "US": "United States", "NG": "Nigeria"}


def _facts(**kwargs) -> dict:
    base = {"funding_mentions": [], "deadline_mentions": [], "level_mentions": []}
    base.update(kwargs)
    return base


def test_a_clean_unambiguous_candidate_resolves_every_field() -> None:
    derived = derive_cycle_facts_from_extraction(
        raw_title="UCL Mathematics Scholarship",
        raw_excerpt="A scholarship for the United Kingdom.",
        page_text="This scholarship is fully funded and open to Master's students "
        "in the United Kingdom, deadline March 15, 2027.",
        extracted_facts=_facts(level_mentions=["masters"], deadline_mentions=["March 15, 2027"]),
        country_names=COUNTRY_NAMES,
    )
    assert derived is not None
    assert derived.destinations == ["GB"]
    assert derived.levels == ["masters"]
    assert derived.award_type == "scholarship"
    assert derived.funding_type == "fully_funded"
    assert derived.deadline_at == datetime(2027, 3, 15, tzinfo=UTC)


def test_two_supported_destinations_named_is_ambiguous() -> None:
    derived = derive_cycle_facts_from_extraction(
        raw_title="Award",
        raw_excerpt="scholarship",
        page_text="Open to study in the United Kingdom or the United States. scholarship",
        extracted_facts=_facts(level_mentions=["masters"]),
        country_names=COUNTRY_NAMES,
    )
    assert derived is None


def test_a_supported_and_an_out_of_scope_country_together_is_ambiguous() -> None:
    derived = derive_cycle_facts_from_extraction(
        raw_title="Award",
        raw_excerpt="scholarship",
        page_text="Open to study in the United Kingdom, for citizens of Nigeria. scholarship",
        extracted_facts=_facts(level_mentions=["masters"]),
        country_names=COUNTRY_NAMES,
    )
    assert derived is None


def test_no_destination_named_at_all_is_ambiguous() -> None:
    derived = derive_cycle_facts_from_extraction(
        raw_title="Award",
        raw_excerpt="scholarship",
        page_text="A generous scholarship for graduate students.",
        extracted_facts=_facts(level_mentions=["masters"]),
        country_names=COUNTRY_NAMES,
    )
    assert derived is None


def test_no_resolvable_level_fails_closed() -> None:
    derived = derive_cycle_facts_from_extraction(
        raw_title="Award",
        raw_excerpt="scholarship",
        page_text="Open to study in the United Kingdom. scholarship",
        extracted_facts=_facts(level_mentions=[]),
        country_names=COUNTRY_NAMES,
    )
    assert derived is None


def test_an_unmapped_level_is_dropped_not_forced() -> None:
    """"bachelors" isn't in the current degree taxonomy - it's dropped, not
    forced into the nearest thing, while a real resolvable level still
    lets the candidate qualify."""
    derived = derive_cycle_facts_from_extraction(
        raw_title="Award",
        raw_excerpt="scholarship",
        page_text="Open to study in the United Kingdom. scholarship",
        extracted_facts=_facts(level_mentions=["masters", "bachelors"]),
        country_names=COUNTRY_NAMES,
    )
    assert derived is not None
    assert derived.levels == ["masters"]


def test_award_type_must_agree_between_aggregator_and_real_page() -> None:
    derived = derive_cycle_facts_from_extraction(
        raw_title="Award",
        raw_excerpt="a scholarship",
        page_text="Open to study in the United Kingdom - this is a fellowship.",
        extracted_facts=_facts(level_mentions=["masters"]),
        country_names=COUNTRY_NAMES,
    )
    assert derived is None


def test_no_funding_type_phrase_leaves_it_unset() -> None:
    derived = derive_cycle_facts_from_extraction(
        raw_title="Award",
        raw_excerpt="scholarship",
        page_text="Open to study in the United Kingdom. scholarship",
        extracted_facts=_facts(level_mentions=["masters"]),
        country_names=COUNTRY_NAMES,
    )
    assert derived is not None
    assert derived.funding_type is None


def test_no_deadline_mention_leaves_deadline_at_none() -> None:
    derived = derive_cycle_facts_from_extraction(
        raw_title="Award",
        raw_excerpt="scholarship",
        page_text="Open to study in the United Kingdom. scholarship",
        extracted_facts=_facts(level_mentions=["masters"]),
        country_names=COUNTRY_NAMES,
    )
    assert derived is not None
    assert derived.deadline_at is None
