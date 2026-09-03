import pytest

from app.domain.taxonomy import normalize_search_filters


def test_aliases_are_normalized() -> None:
    origin, destinations, degree, field = normalize_search_filters("ng", ["ca"], "masters", "MPH")
    assert origin == "NG"
    assert destinations == {"CA"}
    assert degree == "masters"
    assert field == "public_health"


def test_unknown_taxonomy_value_is_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_search_filters("NG", ["XX"], "masters", "public_health")
