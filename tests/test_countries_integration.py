"""Mirroring Core's country catalogue, and searching against it."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from app.domain.countries import SEED_COUNTRIES, SUPPORTED_DESTINATIONS, CountryVocabulary
from app.domain.models import Country
from app.domain.taxonomy import normalize_search_filters
from app.infra.core_catalogue import CatalogueEntry
from app.infra.countries import load_vocabulary, sync_countries
from tests.conftest import requires_db

pytestmark = requires_db


class _FakeCore:
    """Stands in for Core's catalogue endpoint."""

    def __init__(self, entries: list[CatalogueEntry]) -> None:
        self.entries = entries
        self.calls: list[str] = []

    async def list_catalogue(self, name: str) -> list[CatalogueEntry]:
        self.calls.append(name)
        return self.entries


def _entry(code: str, name: str) -> CatalogueEntry:
    return CatalogueEntry(code=code, display_name=name, core_id=None)


async def test_sync_mirrors_every_country(db) -> None:
    core: Any = _FakeCore([_entry("NG", "Nigeria"), _entry("CA", "Canada"), _entry("KE", "Kenya")])
    assert await sync_countries(db, core) == {"received": 3}
    assert core.calls == ["countries"]

    rows = {row.code: row.display_name for row in await db.scalars(select(Country))}
    assert rows == {"NG": "Nigeria", "CA": "Canada", "KE": "Kenya"}


async def test_sync_is_idempotent_and_refreshes_names(db) -> None:
    await sync_countries(db, _FakeCore([_entry("NG", "Nigeria")]))
    await sync_countries(db, _FakeCore([_entry("NG", "Federal Republic of Nigeria")]))

    rows = list(await db.scalars(select(Country)))
    assert len(rows) == 1, "a repeated sync must not duplicate a country"
    assert rows[0].display_name == "Federal Republic of Nigeria"


async def test_sync_never_overwrites_finder_coverage(db) -> None:
    """Coverage is a Finder decision; Core knows nothing about it."""
    await sync_countries(db, _FakeCore([_entry("KE", "Kenya")]))
    kenya = await db.scalar(select(Country).where(Country.code == "KE"))
    kenya.is_supported_destination = True
    await db.commit()

    await sync_countries(db, _FakeCore([_entry("KE", "Kenya")]))
    await db.refresh(kenya)
    assert kenya.is_supported_destination is True


async def test_an_empty_response_is_refused(db) -> None:
    """A truncated fetch must not empty the vocabulary search validates against."""
    await sync_countries(db, _FakeCore([_entry("NG", "Nigeria")]))
    with pytest.raises(ValueError, match="no countries"):
        await sync_countries(db, _FakeCore([]))
    assert len(list(await db.scalars(select(Country)))) == 1


async def test_a_country_missing_from_core_is_kept(db) -> None:
    await sync_countries(db, _FakeCore([_entry("NG", "Nigeria"), _entry("KE", "Kenya")]))
    await sync_countries(db, _FakeCore([_entry("NG", "Nigeria")]))
    codes = {row.code for row in await db.scalars(select(Country))}
    assert codes == {"NG", "KE"}, "rows elsewhere still refer to it by code"


async def test_the_seed_stands_in_before_the_first_sync(db) -> None:
    vocabulary = await load_vocabulary(db)
    assert vocabulary.names == SEED_COUNTRIES
    assert vocabulary.destinations == SUPPORTED_DESTINATIONS


async def test_the_mirror_is_used_once_populated(db) -> None:
    await sync_countries(db, _FakeCore([_entry("NG", "Nigeria"), _entry("CA", "Canada")]))
    vocabulary = await load_vocabulary(db)
    assert vocabulary.names == {"NG": "Nigeria", "CA": "Canada"}
    assert "CA" in vocabulary.destinations


async def test_taxonomies_separates_origins_from_destinations(db, client) -> None:
    await sync_countries(db, _FakeCore([_entry("NG", "Nigeria"), _entry("CA", "Canada")]))
    body = (await client.get("/api/v1/taxonomies")).json()
    assert {item["code"] for item in body["countries"]} == {"NG", "CA"}
    assert {item["code"] for item in body["destinations"]} == {"CA"}
    assert {item["code"] for item in body["degrees"]} == {"masters", "doctorate"}
    assert {item["code"] for item in body["award_types"]} == {
        "scholarship", "fellowship", "assistantship", "studentship", "grant",
    }


async def test_search_accepts_any_origin_and_runs_for_covered_destinations(db, client) -> None:
    await sync_countries(db, _FakeCore([_entry("KE", "Kenya"), _entry("CA", "Canada")]))
    base = {"program_level": "phd", "field": "public_health"}

    ok = await client.post(
        "/api/v1/search", json={**base, "origin_country": "KE", "target_countries": ["CA"]}
    )
    assert ok.status_code == 200, ok.text

    # Kenya is a valid origin but the index has no verified coverage for it as
    # a *destination*. The search still runs (200, real zero) rather than
    # refusing the request outright - a real country with no coverage yet is
    # not the same failure as an unrecognised one, and is disclosed via
    # `meta.warnings` instead of a 422.
    uncovered = await client.post(
        "/api/v1/search", json={**base, "origin_country": "KE", "target_countries": ["KE"]}
    )
    assert uncovered.status_code == 200, uncovered.text
    assert uncovered.json()["data"] == []
    assert "no_verified_coverage:KE" in uncovered.json()["meta"]["warnings"]

    # An outright-unrecognised code is still refused.
    refused = await client.post(
        "/api/v1/search", json={**base, "origin_country": "KE", "target_countries": ["ZZ"]}
    )
    assert refused.status_code == 422


def test_origin_is_wider_than_destination() -> None:
    vocabulary = CountryVocabulary(
        names={"NG": "Nigeria", "CA": "Canada"}, destinations=frozenset({"CA"})
    )
    assert vocabulary.origin("ng") == "NG"
    with pytest.raises(ValueError, match="coverage"):
        vocabulary.destination("NG")
    with pytest.raises(ValueError, match="Unsupported country"):
        vocabulary.origin("ZZ")


def test_normalisation_falls_back_to_the_seed_without_a_vocabulary() -> None:
    origin, destinations, uncovered, degree, field = normalize_search_filters(
        "NG", ["CA"], "phd", "public health"
    )
    assert (origin, destinations, uncovered, degree, field) == (
        "NG",
        frozenset({"CA"}),
        frozenset(),
        "doctorate",
        "public_health",
    )
