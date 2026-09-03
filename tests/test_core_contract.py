"""Vocabularies the Finder shares with Core.

Degree levels are a closed four-row vocabulary that Core states users cannot
add to, and the Finder deliberately offers only two of them. Mirroring it at
runtime would import levels the product must not offer and put a network call
in front of four constants, so the codes are held locally and the agreement is
pinned here instead: a test fails at CI time rather than a handoff failing in
production.

Update this list only alongside a checked change in Core.
"""

from __future__ import annotations

from app.domain.taxonomy import TAXONOMY

#: Core's `degree_levels.slug` values, ISCED 2011 aligned.
#: Source: Core migration `m2_degree_levels_aligned_to_isced`.
#:     diploma    Certificate / Diploma   ISCED 4-5
#:     bachelors  Bachelor's Degree       ISCED 6
#:     masters    Master's Degree         ISCED 7
#:     doctorate  Doctorate (PhD)         ISCED 8
CORE_DEGREE_SLUGS = frozenset({"diploma", "bachelors", "masters", "doctorate"})

#: Core renamed `phd` to `doctorate` in that migration. The Finder accepts the
#: old spelling as an input alias so a client may send either, but it must
#: never leave this service as `phd`.
CORE_RETIRED_DEGREE_SLUGS = frozenset({"phd"})


def test_finder_degree_codes_are_core_slugs() -> None:
    """A join intent forwards program_level; Core cannot resolve a code it lacks."""
    unknown = set(TAXONOMY.degrees) - CORE_DEGREE_SLUGS
    assert not unknown, f"degree codes Core does not hold: {sorted(unknown)}"


def test_finder_offers_only_graduate_levels() -> None:
    """The product is for Master's and PhD applicants, so it is a strict subset."""
    assert set(TAXONOMY.degrees) == {"masters", "doctorate"}


def test_no_retired_core_slug_is_canonical() -> None:
    assert not set(TAXONOMY.degrees) & CORE_RETIRED_DEGREE_SLUGS
    for retired in CORE_RETIRED_DEGREE_SLUGS:
        # Accepted on the way in, normalised on the way out.
        assert TAXONOMY.degree(retired) in CORE_DEGREE_SLUGS


def test_every_degree_alias_resolves_to_a_core_slug() -> None:
    for alias, code in TAXONOMY.degree_aliases.items():
        assert code in CORE_DEGREE_SLUGS, f"alias {alias!r} maps outside Core's vocabulary"
        assert code in TAXONOMY.degrees, (
            f"alias {alias!r} maps to a level the Finder does not offer"
        )
