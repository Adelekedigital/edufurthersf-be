"""Creating and listing the sources the crawler may read."""

from __future__ import annotations

from tests.conftest import requires_db

pytestmark = requires_db

AUTH = {"X-Service-Token": "internal-service-token"}

VALID_SOURCE = {
    "name": "ScholarshipRegion",
    "source_type": "aggregator",
    "authority_grade": "C",
    "approved_domains": ["ScholarshipRegion.com"],
    "active": True,
}


async def test_creating_a_source_requires_authentication(client) -> None:
    assert (
        await client.post("/api/v1/internal/admin/sources", json=VALID_SOURCE)
    ).status_code == 401


async def test_listing_sources_requires_authentication(client) -> None:
    assert (await client.get("/api/v1/internal/admin/sources")).status_code == 401


async def test_a_created_source_is_returned_and_listed(client) -> None:
    created = await client.post("/api/v1/internal/admin/sources", json=VALID_SOURCE, headers=AUTH)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "ScholarshipRegion"
    # Domains are normalised: lowercase, no leading dot.
    assert body["approved_domains"] == ["scholarshipregion.com"]

    listed = await client.get("/api/v1/internal/admin/sources", headers=AUTH)
    assert listed.status_code == 200
    assert [row["source_id"] for row in listed.json()["data"]] == [body["source_id"]]


async def test_an_invalid_authority_grade_is_refused(client) -> None:
    response = await client.post(
        "/api/v1/internal/admin/sources",
        json={**VALID_SOURCE, "authority_grade": "Z"},
        headers=AUTH,
    )
    assert response.status_code == 422


async def test_at_least_one_domain_is_required(client) -> None:
    response = await client.post(
        "/api/v1/internal/admin/sources",
        json={**VALID_SOURCE, "approved_domains": []},
        headers=AUTH,
    )
    assert response.status_code == 422


async def test_deactivating_a_source_requires_authentication(client) -> None:
    created = await client.post("/api/v1/internal/admin/sources", json=VALID_SOURCE, headers=AUTH)
    source_id = created.json()["source_id"]
    response = await client.post(f"/api/v1/internal/admin/sources/{source_id}/deactivate")
    assert response.status_code == 401


async def test_deactivating_a_source_stops_it_being_listed_as_active(client) -> None:
    created = await client.post("/api/v1/internal/admin/sources", json=VALID_SOURCE, headers=AUTH)
    source_id = created.json()["source_id"]

    response = await client.post(
        f"/api/v1/internal/admin/sources/{source_id}/deactivate", headers=AUTH
    )
    assert response.status_code == 200, response.text
    assert response.json()["active"] is False

    listed = await client.get("/api/v1/internal/admin/sources", headers=AUTH)
    assert [row["active"] for row in listed.json()["data"] if row["source_id"] == source_id] == [
        False
    ]


async def test_deactivating_an_unknown_source_is_a_404(client) -> None:
    response = await client.post(
        "/api/v1/internal/admin/sources/01a06530-b2ef-7617-b74e-c22c6e4053fa/deactivate",
        headers=AUTH,
    )
    assert response.status_code == 404
