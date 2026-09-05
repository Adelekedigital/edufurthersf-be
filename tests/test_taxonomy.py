import pytest

from app.domain.countries import CountryVocabulary
from app.domain.taxonomy import TAXONOMY, normalize_search_filters

#: France is a real, nameable country with no verified destination coverage -
#: distinct from "ZZ" below, which isn't a country in this vocabulary at all.
VOCAB = CountryVocabulary(
    names={"NG": "Nigeria", "CA": "Canada", "FR": "France"},
    destinations=frozenset({"CA"}),
)


def test_aliases_are_normalized() -> None:
    origin, covered, uncovered, degree, field = normalize_search_filters(
        "ng", ["ca"], "masters", "MPH", VOCAB
    )
    assert origin == "NG"
    assert covered == {"CA"}
    assert uncovered == set()
    assert degree == "masters"
    assert field == "public_health"


def test_an_unrecognised_country_is_rejected() -> None:
    """Not a real country at all - distinct from a real country we simply
    don't have verified destination coverage for."""
    with pytest.raises(ValueError):
        normalize_search_filters("NG", ["ZZ"], "masters", "public_health", VOCAB)


def test_a_real_country_without_coverage_is_not_rejected() -> None:
    """The search still runs for whichever destinations are covered - it
    never refuses the whole request because one requested destination, real
    but uncovered, was included alongside a covered one."""
    origin, covered, uncovered, _, _ = normalize_search_filters(
        "NG", ["CA", "FR"], "masters", "public_health", VOCAB
    )
    assert covered == {"CA"}
    assert uncovered == {"FR"}


def test_every_requested_destination_uncovered_still_does_not_raise() -> None:
    _, covered, uncovered, _, _ = normalize_search_filters(
        "NG", ["FR"], "masters", "public_health", VOCAB
    )
    assert covered == set()
    assert uncovered == {"FR"}


def test_no_field_preference_passes_through_as_none() -> None:
    """The taxonomy only holds two field codes - forcing a choice between
    exactly two subjects would misrepresent every other field of study."""
    _, _, _, _, field = normalize_search_filters("NG", ["CA"], "masters", None, VOCAB)
    assert field is None
    _, _, _, _, field = normalize_search_filters("NG", ["CA"], "masters", "", VOCAB)
    assert field is None


def test_phd_resolves_to_the_core_aligned_code() -> None:
    """A join intent forwards this value; Core holds `doctorate`, not `phd`."""
    assert TAXONOMY.degree("phd") == "doctorate"
    assert TAXONOMY.degree("PhD") == "doctorate"
    assert TAXONOMY.degree("doctorate") == "doctorate"
    assert TAXONOMY.degrees["doctorate"] == "PhD", "the label stays PhD"


def test_master_aliases_resolve() -> None:
    assert TAXONOMY.degree("MSc") == "masters"
    assert TAXONOMY.degree("masters") == "masters"


def test_an_unknown_degree_is_refused() -> None:
    with pytest.raises(ValueError):
        TAXONOMY.degree("postdoc")
