from dataclasses import dataclass


@dataclass(frozen=True)
class Taxonomy:
    version: str
    countries: dict[str, str]
    degrees: dict[str, str]
    fields: dict[str, str]
    aliases: dict[str, str]

    def country(self, value: str) -> str:
        code = value.strip().upper()
        if code not in self.countries:
            raise ValueError("Unsupported country")
        return code

    def degree(self, value: str) -> str:
        code = value.strip().lower()
        if code not in self.degrees:
            raise ValueError("Unsupported degree level")
        return code

    def field(self, value: str) -> str:
        code = value.strip().lower()
        code = self.aliases.get(code, code)
        if code not in self.fields:
            raise ValueError("Unsupported field")
        return code


TAXONOMY = Taxonomy(
    version="taxonomy-v1",
    countries={"NG": "Nigeria", "CA": "Canada", "GB": "United Kingdom", "US": "United States"},
    degrees={"masters": "Master’s", "phd": "PhD"},
    fields={"public_health": "Public Health", "computer_science": "Computer Science"},
    aliases={
        "public health": "public_health",
        "mph": "public_health",
        "computer science": "computer_science",
        "cs": "computer_science",
    },
)


def normalize_search_filters(
    origin_country: str, target_countries: list[str], program_level: str, field: str
) -> tuple[str, frozenset[str], str, str]:
    origin = TAXONOMY.country(origin_country)
    destinations = frozenset(TAXONOMY.country(value) for value in target_countries)
    if not destinations:
        raise ValueError("At least one destination is required")
    return origin, destinations, TAXONOMY.degree(program_level), TAXONOMY.field(field)
