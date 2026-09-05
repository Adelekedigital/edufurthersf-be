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
    field: str | None,
    countries: CountryVocabulary | None = None,
) -> tuple[str, frozenset[str], frozenset[str], str, str | None]:
    """Normalise the five inputs, or say which one is unsupported.

    Countries come from the mirrored vocabulary when one is supplied, so origin
    accepts any country Core publishes while destinations stay limited to
    verified coverage - but unlike the publish path (which must keep refusing
    a destination outside coverage, since that would be a false claim baked
    into the catalogue), a *search* for an uncovered destination is never
    refused outright. Every requested destination is validated as a real
    country (`vocabulary.origin`, not `vocabulary.destination` - that method
    stays strict for publish), then split into `covered` (searched for real)
    and `uncovered` (a genuine, nameable country we just don't have verified
    coverage for yet). The caller surfaces `uncovered` as an explicit warning
    rather than silently returning fewer results than requested, or refusing
    the whole search because one destination among several isn't covered yet.

    `field` is the one genuinely optional filter: the taxonomy only holds two
    codes today, so forcing every searcher to pick one of exactly two subjects
    misrepresents anyone whose real field is neither - a Law or Business
    applicant had no honest value to send. `None` (or an empty string) means
    "no field preference," validated the same way `evaluate_match` already
    treats a scholarship's own `field_mode="unknown"`: not excluded by field.
    """
    vocabulary = countries or CountryVocabulary(
        names=dict(SEED_COUNTRIES), destinations=SUPPORTED_DESTINATIONS
    )
    origin = vocabulary.origin(origin_country)
    requested = frozenset(vocabulary.origin(value) for value in target_countries)
    covered = frozenset(code for code in requested if code in vocabulary.destinations)
    uncovered = requested - covered
    normalized_field = TAXONOMY.field(field) if field else None
    return origin, covered, uncovered, TAXONOMY.degree(program_level), normalized_field
