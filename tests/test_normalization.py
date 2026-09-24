import pytest

from app.domain.normalization import normalize_discovery


def test_normalization_is_stable_and_whitespace_insensitive() -> None:
    first = normalize_discovery("  Global   Health Award ")
    second = normalize_discovery("Global Health Award")
    assert first == second
    assert first.identity_key == "award|global|health"


# --- an accent must not fragment an identity key ------------------------

SOFT_HYPHEN = "­"


@pytest.mark.parametrize(
    ("accented", "plain"),
    [
        ("Koç University Scholarship", "Koc University Scholarship"),
        ("Heinrich Böll Foundation", "Heinrich Boll Foundation"),
        ("Marie Skłodowska-Curie Actions", "Marie Sklodowska-Curie Actions"),
        ("Türkiye Burslari", "Turkiye Burslari"),
        ("Côte d'Azur University", "Cote d'Azur University"),
        ("Nord Øst Fond", "Nord Ost Fond"),
        ("Gdańsk Stipend", "Gdansk Stipend"),
        ("Émile Boutmy Scholarship", "Emile Boutmy Scholarship"),
    ],
)
def test_the_same_award_keys_the_same_with_or_without_accents(accented, plain):
    """The token pattern is `[a-z0-9]+`, so anything outside it separates
    rather than being ignored - which fragments a name instead of merely
    altering it. "Koç" keyed as `ko`, "Böll" as `b|ll`. An award reported
    with accents by one source never matched the same award reported
    without them by another."""
    assert normalize_discovery(accented).identity_key == normalize_discovery(plain).identity_key


def test_an_invisible_character_does_not_split_a_word():
    """A soft hyphen renders as nothing and is invisible in a diff, but
    splits the token: "We<shy>ber" keyed as `we|ber`."""
    assert (
        normalize_discovery(f"Max We{SOFT_HYPHEN}ber Program").identity_key
        == normalize_discovery("Max Weber Program").identity_key
    )


def test_folding_does_not_merge_distinct_awards():
    """Widening what counts as the same award is the dangerous direction:
    two different scholarships sharing a key are deduplicated into one, and
    the loser disappears. Checked over 1,808 live discoveries before the
    change - 30 keys repaired, zero groups merged."""
    assert (
        normalize_discovery("Oxford Clarendon Scholarship").identity_key
        != normalize_discovery("Cambridge Gates Scholarship").identity_key
    )
    assert (
        normalize_discovery("Koç University Award").identity_key
        != normalize_discovery("Bogazici University Award").identity_key
    )


def test_a_name_that_is_wholly_non_ascii_still_yields_a_key():
    """Previously this produced an empty key, which would make every such
    record identical to every other."""
    assert normalize_discovery("Éçöü").identity_key != ""
