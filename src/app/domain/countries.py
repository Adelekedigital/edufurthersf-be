"""Country vocabulary rules.

Origin and destination are not the same list. Origin is a citizenship the
student states, and restricting it to the countries the index happens to cover
would turn "we have nothing for you yet" into "you do not exist". Destination is
where the index actually has verified coverage, which is a Finder decision and
much smaller.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Destinations the index covers. Owned here rather than mirrored from Core:
#: it records verified coverage, not a fact about the country.
SUPPORTED_DESTINATIONS = frozenset({"CA", "GB", "US", "DE", "FI"})

#: Stands in until the mirror is populated, so a fresh environment can still
#: answer searches. Not the authoritative list — Core's catalogue is.
SEED_COUNTRIES: dict[str, str] = {
    "NG": "Nigeria",
    "CA": "Canada",
    "GB": "United Kingdom",
    "US": "United States",
    "DE": "Germany",
    "FI": "Finland",
}


@dataclass(frozen=True)
class CountryVocabulary:
    names: dict[str, str]
    destinations: frozenset[str]

    def origin(self, value: str) -> str:
        """Normalise a country of origin: any country Core publishes."""
        code = value.strip().upper()
        if code not in self.names:
            raise ValueError("Unsupported country")
        return code

    def destination(self, value: str) -> str:
        """Normalise a study destination: only where coverage exists.

        A destination outside coverage is refused rather than silently returning
        nothing, so the interface can say the search was not run for it instead
        of implying the index looked and found nothing.
        """
        code = self.origin(value)
        if code not in self.destinations:
            raise ValueError(f"No verified coverage for destination {code}")
        return code
