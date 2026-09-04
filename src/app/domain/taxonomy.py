from dataclasses import dataclass

from app.domain.countries import (
    SEED_COUNTRIES,
    SUPPORTED_DESTINATIONS,
    CountryVocabulary,
)


@dataclass(frozen=True)
class Taxonomy:
    version: str
    countries: dict[str, str]
    degrees: dict[str, str]
    fields: dict[str, str]
    aliases: dict[str, str]
    degree_aliases: dict[str, str]
    award_types: dict[str, str]

    def country(self, value: str) -> str:
        code = value.strip().upper()
        if code not in self.countries:
            raise ValueError("Unsupported country")
        return code

    def degree(self, value: str) -> str:
        code = value.strip().lower()
        code = self.degree_aliases.get(code, code)
        if code not in self.degrees:
            raise ValueError("Unsupported degree level")
        return code

    def field(self, value: str) -> str:
        code = value.strip().lower()
        code = self.aliases.get(code, code)
        if code not in self.fields:
            raise ValueError("Unsupported field")
        return code

    def award_type(self, value: str) -> str:
        code = value.strip().lower()
        if code not in self.award_types:
            raise ValueError("Unsupported award type")
        return code


TAXONOMY = Taxonomy(
    version="taxonomy-v1",
    countries={"NG": "Nigeria", "CA": "Canada", "GB": "United Kingdom", "US": "United States"},
    # Codes are ISCED-aligned to match Core's `degree_levels` slugs, because a
    # join intent forwards this value and Core cannot resolve one it does not
    # hold. The label stays "PhD"; only the wire code is `doctorate`.
    degrees={"masters": "Master’s", "doctorate": "PhD"},
    fields={"public_health": "Public Health", "computer_science": "Computer Science"},
    aliases={
        "public health": "public_health",
        "mph": "public_health",
        "computer science": "computer_science",
        "cs": "computer_science",
    },
    degree_aliases={
        "phd": "doctorate",
        "ph.d": "doctorate",
        "ph.d.": "doctorate",
        "doctoral": "doctorate",
        "master's": "masters",
        "master": "masters",
        "msc": "masters",
        "ma": "masters",
        "mba": "masters",
    },
    # What kind of award this is, distinct from what it's for (degree/field) or
    # who funds it (provider). A lab's paid research assistantship and a
    # merit-based tuition scholarship are both legitimate catalog entries, but
    # a searcher deserves to know which one they're looking at.
    award_types={
        "scholarship": "Scholarship",
        "fellowship": "Fellowship",
        "assistantship": "Assistantship",
        "studentship": "Studentship",
        "grant": "Grant",
    },
)


def normalize_search_filters(
    origin_country: str,
    target_countries: list[str],
    program_level: str,
    field: str,
    countries: CountryVocabulary | None = None,
) -> tuple[str, frozenset[str], str, str]:
    """Normalise the four inputs, or say which one is unsupported.

    Countries come from the mirrored vocabulary when one is supplied, so origin
    accepts any country Core publishes while destinations stay limited to
    verified coverage.
    """
    vocabulary = countries or CountryVocabulary(
        names=dict(SEED_COUNTRIES), destinations=SUPPORTED_DESTINATIONS
    )
    origin = vocabulary.origin(origin_country)
    destinations = frozenset(vocabulary.destination(value) for value in target_countries)
    if not destinations:
        raise ValueError("At least one destination is required")
    return origin, destinations, TAXONOMY.degree(program_level), TAXONOMY.field(field)
