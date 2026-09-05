"""End-to-end search behaviour against a real database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.domain.models import (
    AnonymousSession,
    Country,
    Provider,
    PublicStatus,
    RecordState,
    Scholarship,
    ScholarshipCycle,
    Search,
)
from tests.conftest import requires_db

pytestmark = requires_db

SEARCH = {
    "origin_country": "NG",
    "program_level": "masters",
    "field": "public_health",
    "target_countries": ["CA", "GB"],
}

CONFIRMED_FACTS = {
    "destinations": ["CA"],
    "levels": ["masters"],
    "origin_mode": "unrestricted",
    "field_mode": "restricted",
    "fields": ["public_health"],
    "evidence_fresh": True,
}
POSSIBLE_FACTS = {**CONFIRMED_FACTS, "origin_mode": "unknown", "field_mode": "unknown"}


async def _publish(db, *, slug: str, facts: dict, status: PublicStatus, deadline=None) -> None:
    provider = Provider(name=f"Provider {slug}", approved_domains=["example.test"])
    db.add(provider)
    await db.flush()
    scholarship = Scholarship(
        provider_id=provider.provider_id,
        slug=slug,
        name=f"Award {slug}",
        official_home_url="https://example.test/award",
        award_type="scholarship",
        lifecycle_state=RecordState.published,
    )
    db.add(scholarship)
    await db.flush()
    cycle_facts = dict(facts)
    if deadline is not None:
        cycle_facts["deadline_at"] = deadline.isoformat()
    db.add(
        ScholarshipCycle(
            scholarship_id=scholarship.scholarship_id,
            provider_cycle_key=f"{slug}-2026",
            official_cycle_url="https://example.test/award/apply",
            public_status=status,
            facts=cycle_facts,
        )
    )
    await db.commit()


async def test_search_returns_published_records(db, client) -> None:
    await _publish(db, slug="a", facts=CONFIRMED_FACTS, status=PublicStatus.open_verified)
    response = await client.post("/api/v1/search", json=SEARCH)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["name"] for item in body["data"]] == ["Award a"]
    assert body["meta"]["confirmed_counts"] == {"open_verified": 1}


async def test_expired_deadline_is_never_returned_as_open(db, client) -> None:
    """A passed deadline must downgrade on read, with no sweep required."""
    await _publish(
        db,
        slug="expired",
        facts=CONFIRMED_FACTS,
        status=PublicStatus.open_verified,
        deadline=datetime.now(UTC) - timedelta(days=1),
    )
    body = (await client.post("/api/v1/search", json=SEARCH)).json()
    assert body["data"][0]["status"] == "status_unknown"
    assert body["meta"]["confirmed_counts"].get("open_verified") is None
    assert any("re-verification" in caveat for caveat in body["data"][0]["caveats"])


async def test_confirmed_matches_rank_above_possible_ones(db, client) -> None:
    await _publish(db, slug="possible", facts=POSSIBLE_FACTS, status=PublicStatus.open_verified)
    await _publish(db, slug="confirmed", facts=CONFIRMED_FACTS, status=PublicStatus.open_verified)
    body = (await client.post("/api/v1/search", json=SEARCH)).json()
    assert [item["fit"] for item in body["data"]] == ["confirmed", "possible"]
    assert body["meta"]["possible_match_count"] == 1


async def test_search_persists_the_session_and_search(db, client) -> None:
    """The row must survive the request; nothing downstream works otherwise."""
    response = await client.post("/api/v1/search", json=SEARCH)
    search_id = response.json()["meta"]["search_id"]
    stored = await db.scalar(select(Search).where(Search.search_id == search_id))
    assert stored is not None
    assert stored.filters["origin_country"] == "NG"
    assert await db.scalar(select(AnonymousSession)) is not None


async def test_session_cookie_is_not_the_primary_key(db, client) -> None:
    response = await client.post("/api/v1/search", json=SEARCH)
    cookie = response.cookies.get("finder_session")
    session = await db.scalar(select(AnonymousSession))
    assert cookie == session.pseudonymous_id
    assert cookie != str(session.session_id)


@pytest.mark.parametrize("bad_field", ["astrophysics", "'; drop table scholarships; --"])
async def test_unsupported_filters_are_rejected(client, bad_field: str) -> None:
    response = await client.post("/api/v1/search", json={**SEARCH, "field": bad_field})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


async def _seed_countries(db) -> None:
    """NG (origin), CA (a real, verified-coverage destination), FR (a real
    country with no verified destination coverage yet)."""
    for code, name, is_destination in (
        ("NG", "Nigeria", False),
        ("CA", "Canada", True),
        ("FR", "France", False),
    ):
        db.add(Country(code=code, display_name=name, is_supported_destination=is_destination))
    await db.commit()


async def test_uncovered_destination_alongside_a_covered_one_still_runs(db, client) -> None:
    """The search must never be refused outright because one requested
    destination, among several, isn't verified coverage yet - it runs for
    the covered ones and says explicitly which weren't."""
    await _seed_countries(db)
    await _publish(db, slug="ca-award", facts=CONFIRMED_FACTS, status=PublicStatus.open_verified)
    response = await client.post(
        "/api/v1/search",
        json={**SEARCH, "target_countries": ["CA", "FR"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["name"] for item in body["data"]] == ["Award ca-award"]
    assert "no_verified_coverage:FR" in body["meta"]["warnings"]


async def test_every_requested_destination_uncovered_is_200_not_422(db, client) -> None:
    """A real country with no coverage yet is not the same failure as an
    outright-invalid one - it's an honest, explicit zero, not a 422."""
    await _seed_countries(db)
    response = await client.post(
        "/api/v1/search",
        json={**SEARCH, "target_countries": ["FR"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data"] == []
    assert "no_verified_coverage:FR" in body["meta"]["warnings"]


async def test_an_unrecognised_country_is_still_rejected(db, client) -> None:
    """Distinct from an uncovered-but-real destination: this isn't a
    country at all, and stays a 422."""
    await _seed_countries(db)
    response = await client.post(
        "/api/v1/search",
        json={**SEARCH, "target_countries": ["ZZ"]},
    )
    assert response.status_code == 422


async def test_no_field_preference_still_finds_a_field_restricted_scholarship(db, client) -> None:
    """A searcher whose real field (Law, Business, ...) isn't one of the two
    taxonomy codes must be able to search with no field at all, and still see
    scholarships that are restricted to a *specific* field - they just aren't
    excluded by a preference they never expressed."""
    await _publish(db, slug="cs-only", facts=CONFIRMED_FACTS, status=PublicStatus.open_verified)
    no_field_search = {k: v for k, v in SEARCH.items() if k != "field"}
    body = (await client.post("/api/v1/search", json=no_field_search)).json()
    assert [item["name"] for item in body["data"]] == ["Award cs-only"]
