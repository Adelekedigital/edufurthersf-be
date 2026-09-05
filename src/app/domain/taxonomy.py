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
    #: ISCED-F 2013 broad fields (11 codes) - what a search form offers, since
    #: that's the granularity a real searcher actually thinks in ("Health",
    #: "Engineering"), not a 29-way narrow-field pick list.
    broad_fields: dict[str, str]
    #: ISCED-F 2013 narrow fields (29 codes) - what a scholarship is actually
    #: tagged with at publish time, since a real program is specific
    #: ("Nursing and midwifery" lives under 091 Health). A search's broad
    #: choice is expanded via `narrow_to_broad` before matching against these.
    narrow_fields: dict[str, str]
    #: Narrow code -> its broad parent code. The only bridge between the two
    #: namespaces; never hand-duplicated elsewhere.
    narrow_to_broad: dict[str, str]
    #: Synonyms resolving to a narrow code (scholarship tagging).
    aliases: dict[str, str]
    #: Synonyms resolving to a broad code (search filter).
    broad_aliases: dict[str, str]
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
        """Validate a narrow field code - what a scholarship is tagged with."""
        code = value.strip().lower()
        code = self.aliases.get(code, code)
        if code not in self.narrow_fields:
            raise ValueError("Unsupported field")
        return code

    def broad_field(self, value: str) -> str:
        """Validate a broad field code - what a search filters by."""
        code = value.strip().lower()
        code = self.broad_aliases.get(code, code)
        if code not in self.broad_fields:
            raise ValueError("Unsupported field")
        return code

    def narrow_fields_under(self, broad_code: str) -> frozenset[str]:
        return frozenset(
            narrow for narrow, broad in self.narrow_to_broad.items() if broad == broad_code
        )

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
    # ISCED-F 2013 (UNESCO UIS), broad tier - 11 codes including the
    # standard's "00 Generic" and "10 Services" groups alongside the 9
    # substantive fields.
    broad_fields={
        "generic": "Generic programmes and qualifications",
        "education": "Education",
        "arts_and_humanities": "Arts and humanities",
        "social_sciences_journalism_information": "Social sciences, journalism and information",
        "business_administration_law": "Business, administration and law",
        "natural_sciences_math_stats": "Natural sciences, mathematics and statistics",
        "ict": "Information and Communication Technologies (ICT)",
        "engineering_manufacturing_construction": "Engineering, manufacturing and construction",
        "agriculture_forestry_fisheries_veterinary": (
            "Agriculture, forestry, fisheries and veterinary"
        ),
        "health_and_welfare": "Health and welfare",
        "services": "Services",
    },
    # ISCED-F 2013, narrow tier - all 29 codes, what a scholarship is
    # actually tagged with (see `narrow_to_broad` for the parent mapping).
    narrow_fields={
        "basic_programmes": "Basic programmes and qualifications",
        "literacy_and_numeracy": "Literacy and numeracy",
        "personal_skills_development": "Personal skills and development",
        "education": "Education",
        "arts": "Arts",
        "humanities": "Humanities (except languages)",
        "languages": "Languages",
        "social_behavioural_sciences": "Social and behavioural sciences",
        "journalism_and_information": "Journalism and information",
        "business_and_administration": "Business and administration",
        "law": "Law",
        "biological_sciences": "Biological and related sciences",
        "environment": "Environment",
        "physical_sciences": "Physical sciences",
        "mathematics_and_statistics": "Mathematics and statistics",
        "ict": "Information and Communication Technologies (ICT)",
        "engineering_trades": "Engineering and engineering trades",
        "manufacturing_and_processing": "Manufacturing and processing",
        "architecture_and_construction": "Architecture and construction",
        "agriculture": "Agriculture",
        "forestry": "Forestry",
        "fisheries": "Fisheries",
        "veterinary": "Veterinary",
        "health": "Health",
        "welfare": "Welfare",
        "personal_services": "Personal services",
        "hygiene_occupational_health": "Hygiene and occupational health services",
        "security_services": "Security services",
        "transport_services": "Transport services",
    },
    narrow_to_broad={
        "basic_programmes": "generic",
        "literacy_and_numeracy": "generic",
        "personal_skills_development": "generic",
        "education": "education",
        "arts": "arts_and_humanities",
        "humanities": "arts_and_humanities",
        "languages": "arts_and_humanities",
        "social_behavioural_sciences": "social_sciences_journalism_information",
        "journalism_and_information": "social_sciences_journalism_information",
        "business_and_administration": "business_administration_law",
        "law": "business_administration_law",
        "biological_sciences": "natural_sciences_math_stats",
        "environment": "natural_sciences_math_stats",
        "physical_sciences": "natural_sciences_math_stats",
        "mathematics_and_statistics": "natural_sciences_math_stats",
        "ict": "ict",
        "engineering_trades": "engineering_manufacturing_construction",
        "manufacturing_and_processing": "engineering_manufacturing_construction",
        "architecture_and_construction": "engineering_manufacturing_construction",
        "agriculture": "agriculture_forestry_fisheries_veterinary",
        "forestry": "agriculture_forestry_fisheries_veterinary",
        "fisheries": "agriculture_forestry_fisheries_veterinary",
        "veterinary": "agriculture_forestry_fisheries_veterinary",
        "health": "health_and_welfare",
        "welfare": "health_and_welfare",
        "personal_services": "services",
        "hygiene_occupational_health": "services",
        "security_services": "services",
        "transport_services": "services",
    },
    aliases={
        "public health": "health",
        "mph": "health",
        "computer science": "ict",
        "cs": "ict",
    },
    broad_aliases={
        "public health": "health_and_welfare",
        "mph": "health_and_welfare",
        "computer science": "ict",
        "cs": "ict",
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
) -> tuple[str, frozenset[str], frozenset[str], str, str | None, frozenset[str] | None]:
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

    `field` is the one genuinely optional filter, and it names a *broad*
    ISCED-F code (what a search form offers) - never the narrow code a
    scholarship is actually tagged with. The normalised broad code is
    returned alongside the expansion to every narrow code under that bucket,
    since a scholarship tagged `health` (narrow) must still match a search for
    `health_and_welfare` (broad) - the broad code is what identifies the
    search itself (e.g. for pagination digests), the narrow set is what
    `evaluate_match` actually compares against. `None` (or an empty string)
    means "no field preference," validated the same way `evaluate_match`
    already treats a scholarship's own `field_mode="unknown"`: not excluded by
    field.
    """
    vocabulary = countries or CountryVocabulary(
        names=dict(SEED_COUNTRIES), destinations=SUPPORTED_DESTINATIONS
    )
    origin = vocabulary.origin(origin_country)
    requested = frozenset(vocabulary.origin(value) for value in target_countries)
    covered = frozenset(code for code in requested if code in vocabulary.destinations)
    uncovered = requested - covered
    normalized_field = TAXONOMY.broad_field(field) if field else None
    accepted_fields = TAXONOMY.narrow_fields_under(normalized_field) if normalized_field else None
    return (
        origin,
        covered,
        uncovered,
        TAXONOMY.degree(program_level),
        normalized_field,
        accepted_fields,
    )
