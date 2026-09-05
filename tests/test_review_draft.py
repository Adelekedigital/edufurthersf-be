"""prepare_review's draft logic: explains and proposes, never decides."""

from __future__ import annotations

from app.domain.review_draft import DRAFT_VERSION, _mentioned_countries, draft_review_recommendation

COUNTRY_NAMES = {
    "NG": "Nigeria",
    "CA": "Canada",
    "GB": "United Kingdom",
    "US": "United States",
    "DE": "Germany",
    "FI": "Finland",
}


def test_a_clearly_out_of_scope_country_drafts_a_reject() -> None:
    draft = draft_review_recommendation(
        raw_title="University of Lagos PhD Scholarship",
        raw_excerpt="Open to students studying in Nigeria.",
        extracted_facts=None,
        country_names=COUNTRY_NAMES,
    )
    assert draft["draft_version"] == DRAFT_VERSION
    assert draft["verdict"] == "reject"
    assert any("Nigeria" in line for line in draft["reasoning"])
    assert draft["proposed_award_type"] is None


def test_a_supported_destination_named_alongside_another_country_is_left_ambiguous() -> None:
    """The reject closure only fires when nothing supported is also named -
    a multi-country consortium or a Nigeria-to-UK scheme must not be
    misread as out of scope just because Nigeria is mentioned too."""
    draft = draft_review_recommendation(
        raw_title="UCL Commonwealth Scholarship",
        raw_excerpt="For students from Nigeria to study in the United Kingdom.",
        extracted_facts=None,
        country_names=COUNTRY_NAMES,
    )
    assert draft["verdict"] == "ambiguous"


def test_no_country_named_is_ambiguous_not_a_guess() -> None:
    draft = draft_review_recommendation(
        raw_title="Award A",
        raw_excerpt="A generous scholarship for graduate students.",
        extracted_facts=None,
        country_names=COUNTRY_NAMES,
    )
    assert draft["verdict"] == "ambiguous"


def test_never_drafts_a_confident_pass() -> None:
    """No verdict here can honestly claim to have fetched and cross-checked
    the real official source - that verdict does not exist in this draft."""
    draft = draft_review_recommendation(
        raw_title="Harvard Scholarship",
        raw_excerpt="Open to international students in the United States.",
        extracted_facts={"funding_mentions": ["$50,000"]},
        country_names=COUNTRY_NAMES,
    )
    assert draft["verdict"] in {"ambiguous", "reject"}


def test_extracted_facts_are_carried_through_as_proposed_facts() -> None:
    facts = {"funding_mentions": ["£10,000"], "level_mentions": ["masters"]}
    draft = draft_review_recommendation(
        raw_title="Award A",
        raw_excerpt="An award.",
        extracted_facts=facts,
        country_names=COUNTRY_NAMES,
    )
    assert draft["proposed_facts"] == facts


def test_missing_extracted_facts_propose_an_empty_dict_not_none() -> None:
    draft = draft_review_recommendation(
        raw_title="Award A",
        raw_excerpt="An award.",
        extracted_facts=None,
        country_names=COUNTRY_NAMES,
    )
    assert draft["proposed_facts"] == {}


def test_word_boundary_avoids_a_substring_collision() -> None:
    """"Niger" must not fire inside "Nigeria" - the same shape of name
    collision caught by hand this session (Hamad Bin Khalifa vs Khalifa
    University)."""
    supported, other = _mentioned_countries(
        "University of Lagos, Nigeria", {**COUNTRY_NAMES, "NE": "Niger"}
    )
    assert supported == []
    assert other == ["NG"]
