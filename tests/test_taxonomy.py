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
    origin, covered, uncovered, degree, field, accepted_fields = normalize_search_filters(
        "ng", ["ca"], "masters", "MPH", VOCAB
    )
    assert origin == "NG"
    assert covered == {"CA"}
    assert uncovered == set()
    assert degree == "masters"
    assert field == "health_and_welfare"
    assert accepted_fields == {"health", "welfare"}


def test_an_unrecognised_country_is_rejected() -> None:
    """Not a real country at all - distinct from a real country we simply
    don't have verified destination coverage for."""
    with pytest.raises(ValueError):
        normalize_search_filters("NG", ["ZZ"], "masters", "health_and_welfare", VOCAB)


def test_a_real_country_without_coverage_is_not_rejected() -> None:
    """The search still runs for whichever destinations are covered - it
    never refuses the whole request because one requested destination, real
    but uncovered, was included alongside a covered one."""
    origin, covered, uncovered, _, _, _ = normalize_search_filters(
        "NG", ["CA", "FR"], "masters", "health_and_welfare", VOCAB
    )
    assert covered == {"CA"}
    assert uncovered == {"FR"}


def test_every_requested_destination_uncovered_still_does_not_raise() -> None:
    _, covered, uncovered, _, _, _ = normalize_search_filters(
        "NG", ["FR"], "masters", "health_and_welfare", VOCAB
    )
    assert covered == set()
    assert uncovered == {"FR"}


def test_no_field_preference_passes_through_as_none() -> None:
    """Field is the one genuinely optional filter - forcing a choice among
    the taxonomy's broad fields would misrepresent a searcher with no field
    preference at all."""
    _, _, _, _, field, accepted_fields = normalize_search_filters(
        "NG", ["CA"], "masters", None, VOCAB
    )
    assert field is None
    assert accepted_fields is None
    _, _, _, _, field, accepted_fields = normalize_search_filters(
        "NG", ["CA"], "masters", "", VOCAB
    )
    assert field is None
    assert accepted_fields is None


def test_narrow_fields_under_a_broad_code_resolve_correctly() -> None:
    assert TAXONOMY.narrow_fields_under("ict") == {"ict"}
    assert TAXONOMY.narrow_fields_under("health_and_welfare") == {"health", "welfare"}


def test_narrow_field_validates_against_the_narrow_list_not_the_broad_one() -> None:
    assert TAXONOMY.field("public health") == "health"
    assert TAXONOMY.field("cs") == "ict"
    with pytest.raises(ValueError):
        TAXONOMY.field("health_and_welfare")


def test_broad_field_validates_against_the_broad_list_not_the_narrow_one() -> None:
    assert TAXONOMY.broad_field("computer science") == "ict"
    with pytest.raises(ValueError):
        TAXONOMY.broad_field("health")


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
