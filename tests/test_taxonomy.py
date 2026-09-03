import pytest

from app.domain.taxonomy import TAXONOMY, normalize_search_filters


def test_aliases_are_normalized() -> None:
    origin, destinations, degree, field = normalize_search_filters("ng", ["ca"], "masters", "MPH")
    assert origin == "NG"
    assert destinations == {"CA"}
    assert degree == "masters"
    assert field == "public_health"


def test_unknown_taxonomy_value_is_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_search_filters("NG", ["XX"], "masters", "public_health")


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
