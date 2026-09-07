"""Creating and listing providers - the organizations responsible for an
award, distinct from the sources that report on it. Without this, decide_review's
approve path has no provider_id to hand a real candidate."""

from __future__ import annotations

from tests.conftest import requires_db

pytestmark = requires_db

AUTH = {"X-Service-Token": "internal-service-token"}

VALID_PROVIDER = {
    "name": "Example University",
    "approved_domains": ["Example.EDU"],
}


async def test_creating_a_provider_requires_authentication(client) -> None:
    response = await client.post("/api/v1/internal/admin/providers", json=VALID_PROVIDER)
    assert response.status_code == 401


async def test_listing_providers_requires_authentication(client) -> None:
    assert (await client.get("/api/v1/internal/admin/providers")).status_code == 401


async def test_a_created_provider_is_returned_and_listed(client) -> None:
    created = await client.post(
        "/api/v1/internal/admin/providers", json=VALID_PROVIDER, headers=AUTH
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "Example University"
    assert body["approved_domains"] == ["example.edu"]

    listed = await client.get("/api/v1/internal/admin/providers", headers=AUTH)
    assert listed.status_code == 200
    assert [row["provider_id"] for row in listed.json()["data"]] == [body["provider_id"]]


async def test_at_least_one_domain_is_required(client) -> None:
    response = await client.post(
        "/api/v1/internal/admin/providers",
        json={**VALID_PROVIDER, "approved_domains": []},
        headers=AUTH,
    )
    assert response.status_code == 422


async def test_country_is_optional_and_absent_by_default(client) -> None:
    created = await client.post(
        "/api/v1/internal/admin/providers", json=VALID_PROVIDER, headers=AUTH
    )
    assert created.status_code == 201, created.text
    assert created.json()["country"] is None


async def test_a_providers_own_country_is_stored_and_returned(client) -> None:
    """Any real country, not limited to Finder's covered destinations - a
    provider can be based anywhere, same vocabulary as a searcher's origin."""
    created = await client.post(
        "/api/v1/internal/admin/providers",
        json={**VALID_PROVIDER, "country": "GB"},
        headers=AUTH,
    )
    assert created.status_code == 201, created.text
    assert created.json()["country"] == "GB"

    listed = await client.get("/api/v1/internal/admin/providers", headers=AUTH)
    assert listed.json()["data"][0]["country"] == "GB"


async def test_an_unrecognized_provider_country_is_a_422(client) -> None:
    response = await client.post(
        "/api/v1/internal/admin/providers",
        json={**VALID_PROVIDER, "country": "ZZ"},
        headers=AUTH,
    )
    assert response.status_code == 422
