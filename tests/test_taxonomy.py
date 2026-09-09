import pytest

from app.domain.countries import CountryVocabulary
from app.domain.taxonomy import TAXONOMY, normalize_search_filters

VOCAB = CountryVocabulary(
    names={"NG": "Nigeria", "CA": "Canada", "FR": "France"},
    destinations=frozenset({"CA"}),
)


def test_aliases_and_multiple_degrees_are_normalized() -> None:
    origin, covered, uncovered, degrees, field, accepted_fields = normalize_search_filters(
        "ng", ["ca"], ["masters", "mba"], "health_and_medical_sciences", VOCAB
    )
    assert origin == "NG"
    assert covered == {"CA"}
    assert uncovered == set()
    assert degrees == {"masters", "mba"}
    assert field == "health_and_medical_sciences"
    assert accepted_fields == {"health_and_medical_sciences"}


def test_legacy_field_aliases_normalize_to_canonical_codes() -> None:
    assert TAXONOMY.field("public health") == "health_and_medical_sciences"
    assert TAXONOMY.field("cs") == "technology"


def test_new_field_codes_are_accepted() -> None:
    assert TAXONOMY.broad_field("mathematics_and_statistics") == "mathematics_and_statistics"
    assert TAXONOMY.narrow_fields_under("technology") == {"technology"}


def test_unknown_country_is_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_search_filters("NG", ["ZZ"], ["masters"], "technology", VOCAB)


def test_uncovered_real_destination_is_not_rejected() -> None:
    _, covered, uncovered, _, _, _ = normalize_search_filters(
        "NG", ["CA", "FR"], ["masters"], "technology", VOCAB
    )
    assert covered == {"CA"}
    assert uncovered == {"FR"}


def test_no_field_preference_passes_through_as_none() -> None:
    _, _, _, _, field, accepted_fields = normalize_search_filters(
        "NG", ["CA"], ["masters"], None, VOCAB
    )
    assert field is None
    assert accepted_fields is None


def test_phd_and_mba_are_distinct_degree_codes() -> None:
    assert TAXONOMY.degree("phd") == "doctorate"
    assert TAXONOMY.degree("mba") == "mba"
    assert TAXONOMY.degrees == {"masters": "Master's", "mba": "MBA", "doctorate": "PhD"}
