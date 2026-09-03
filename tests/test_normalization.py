from app.domain.normalization import normalize_discovery


def test_normalization_is_stable_and_whitespace_insensitive() -> None:
    first = normalize_discovery("  Global   Health Award ")
    second = normalize_discovery("Global Health Award")
    assert first == second
    assert first.identity_key == "award|global|health"
