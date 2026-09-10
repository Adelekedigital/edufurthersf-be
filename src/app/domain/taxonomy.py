import logging
from collections.abc import Callable
from dataclasses import dataclass

from app.domain.countries import SEED_COUNTRIES, SUPPORTED_DESTINATIONS, CountryVocabulary

logger = logging.getLogger("app.domain.taxonomy")


@dataclass(frozen=True)
class Taxonomy:
    version: str
    countries: dict[str, str]
    degrees: dict[str, str]
    fields: dict[str, str]
    field_aliases: dict[str, str]
    degree_aliases: dict[str, str]
    award_types: dict[str, str]
    funding_types: dict[str, str]

    def country(self, value: str) -> str:
        code = value.strip().upper()
        if code not in self.countries:
            raise ValueError("Unsupported country")
        return code

    def degree(self, value: str) -> str:
        code = self.degree_aliases.get(value.strip().lower(), value.strip().lower())
        if code not in self.degrees:
            raise ValueError("Unsupported degree level")
        return code

    def field(self, value: str) -> str:
        code = self.field_aliases.get(value.strip().lower(), value.strip().lower())
        if code not in self.fields:
            raise ValueError("Unsupported field")
        return code

    def normalize_fields(self, values: list[str]) -> tuple[list[str], list[str]]:
        """Return canonical field codes and values that need manual review.

        Logs unmapped values so a call site that only consumes the canonical
        half doesn't drop an orphaned/pre-migration code with zero signal.
        """
        return self._normalize_codes(values, self.field, kind="field")

    def normalize_degrees(self, values: list[str]) -> tuple[list[str], list[str]]:
        """Same contract as normalize_fields, for degree-level codes."""
        return self._normalize_codes(values, self.degree, kind="degree")

    def _normalize_codes(
        self, values: list[str], resolver: Callable[[str], str], *, kind: str
    ) -> tuple[list[str], list[str]]:
        canonical: set[str] = set()
        unmapped: set[str] = set()
        for value in values:
            try:
                canonical.add(resolver(value))
            except ValueError:
                unmapped.add(value)
        if unmapped:
            logger.warning(
                "taxonomy_unmapped_values", extra={"kind": kind, "values": sorted(unmapped)}
            )
        return sorted(canonical), sorted(unmapped)

    def broad_field(self, value: str) -> str:
        return self.field(value)

    def narrow_fields_under(self, field_code: str) -> frozenset[str]:
        # The product taxonomy is flat. Keep this method for callers migrating
        # from the old broad/narrow implementation.
        return frozenset({self.field(field_code)})

    def _lookup(self, value: str, table: dict[str, str], label: str) -> str:
        code = value.strip().lower()
        if code not in table:
            raise ValueError(f"Unsupported {label}")
        return code

    def award_type(self, value: str) -> str:
        return self._lookup(value, self.award_types, "award type")

    def funding_type(self, value: str) -> str:
        return self._lookup(value, self.funding_types, "funding type")


TAXONOMY = Taxonomy(
    version="taxonomy-v3",
    countries={
        "NG": "Nigeria",
        "CA": "Canada",
        "GB": "United Kingdom",
        "US": "United States",
        "DE": "Germany",
        "FI": "Finland",
        "AU": "Australia",
    },
    degrees={"masters": "Master's", "mba": "MBA", "doctorate": "PhD"},
    fields={
        "technology": "Technology",
        "engineering": "Engineering",
        "mathematics_and_statistics": "Mathematics and Statistics",
        "natural_sciences": "Natural Sciences",
        "health_and_medical_sciences": "Health and Medical Sciences",
        "business_and_management": "Business and Management",
        "economics_and_development": "Economics and Development",
        "social_sciences": "Social Sciences",
        "law": "Law",
        "public_policy_and_governance": "Public Policy and Governance",
        "education": "Education",
        "arts_humanities_and_design": "Arts, Humanities and Design",
        "agriculture_and_food_systems": "Agriculture and Food Systems",
        "environmental_and_climate_sciences": "Environmental and Climate Sciences",
    },
    field_aliases={
        "ict": "technology",
        "computer science": "technology",
        "cs": "technology",
        "public health": "health_and_medical_sciences",
        "mph": "health_and_medical_sciences",
        "health": "health_and_medical_sciences",
        "welfare": "health_and_medical_sciences",
        "health_and_welfare": "health_and_medical_sciences",
        "business_and_administration": "business_and_management",
        "business_administration_law": "business_and_management",
        "social_behavioural_sciences": "social_sciences",
        "social_sciences_journalism_information": "social_sciences",
        "journalism_and_information": "social_sciences",
        "engineering_trades": "engineering",
        "engineering_manufacturing_construction": "engineering",
        "manufacturing_and_processing": "engineering",
        "architecture_and_construction": "engineering",
        "physical_sciences": "natural_sciences",
        "biological_sciences": "natural_sciences",
        "natural_sciences_math_stats": "natural_sciences",
        "environment": "environmental_and_climate_sciences",
        "agriculture": "agriculture_and_food_systems",
        "forestry": "agriculture_and_food_systems",
        "fisheries": "agriculture_and_food_systems",
        "veterinary": "agriculture_and_food_systems",
        "agriculture_forestry_fisheries_veterinary": "agriculture_and_food_systems",
        "arts_and_humanities": "arts_humanities_and_design",
        "arts": "arts_humanities_and_design",
        "humanities": "arts_humanities_and_design",
        "languages": "arts_humanities_and_design",
        "mathematics": "mathematics_and_statistics",
        "public_policy": "public_policy_and_governance",
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
    },
    award_types={
        "scholarship": "Scholarship",
        "fellowship": "Fellowship",
        "assistantship": "Assistantship",
        "studentship": "Studentship",
        "grant": "Grant",
    },
    funding_types={
        "fully_funded": "Fully funded",
        "partial_funding": "Partial funding",
        "tuition_only": "Tuition only",
        "stipend_only": "Stipend only",
    },
)


def normalize_search_filters(
    origin_country: str,
    target_countries: list[str],
    program_levels: list[str],
    field: str | None,
    countries: CountryVocabulary | None = None,
) -> tuple[
    str,
    frozenset[str],
    frozenset[str],
    frozenset[str],
    str | None,
    frozenset[str] | None,
]:
    vocabulary = countries or CountryVocabulary(
        names=dict(SEED_COUNTRIES), destinations=SUPPORTED_DESTINATIONS
    )
    origin = vocabulary.origin(origin_country)
    requested = frozenset(vocabulary.origin(value) for value in target_countries)
    covered = frozenset(code for code in requested if code in vocabulary.destinations)
    uncovered = requested - covered
    normalized_field = TAXONOMY.field(field) if field else None
    accepted_fields = frozenset({normalized_field}) if normalized_field else None
    degrees = frozenset(TAXONOMY.degree(value) for value in program_levels)
    if not degrees:
        raise ValueError("At least one program level is required")
    return origin, covered, uncovered, degrees, normalized_field, accepted_fields
