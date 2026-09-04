"""The admin scholarship search/list endpoint - for a reviewer or tester
confirming what an import or publish actually produced, across every
lifecycle state, not just what a public applicant would see."""

from __future__ import annotations

from sqlalchemy import select

from app.domain.models import Provider, RecordState, Scholarship
from tests.conftest import requires_db

pytestmark = requires_db

AUTH = {"X-Service-Token": "internal-service-token"}

CYCLE = {
    "provider_cycle_key": "2027-intake",
    "official_cycle_url": "https://example.test/apply",
    "public_status": "open_verified",
    "destinations": ["CA"],
    "levels": ["masters"],
    "origin_mode": "unrestricted",
    "field_mode": "restricted",
    "fields": ["public_health"],
    "evidence_fresh": True,
}


async def _scholarship(
    db, *, name: str, slug: str, lifecycle_state: RecordState = RecordState.needs_review
) -> Scholarship:
    provider = await db.scalar(
        select(Provider).where(Provider.name == "Example University")
    )
    if provider is None:
        provider = Provider(name="Example University", approved_domains=["example.test"])
        db.add(provider)
        await db.flush()
    scholarship = Scholarship(
        provider_id=provider.provider_id,
        slug=slug,
        name=name,
        official_home_url="https://example.test/award",
        lifecycle_state=lifecycle_state,
    )
    db.add(scholarship)
    await db.commit()
    return scholarship


async def test_listing_requires_authentication(client) -> None:
    assert (await client.get("/api/v1/internal/admin/scholarships")).status_code == 401


async def test_every_lifecycle_state_is_visible_with_no_filter(db, client) -> None:
    await _scholarship(db, name="Discovered Award", slug="discovered-award")
    await _scholarship(
        db, name="Withdrawn Award", slug="withdrawn-award", lifecycle_state=RecordState.withdrawn
    )
    response = await client.get("/api/v1/internal/admin/scholarships", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {row["name"] for row in body["data"]} == {"Discovered Award", "Withdrawn Award"}


async def test_q_filters_by_name_case_insensitively(db, client) -> None:
    await _scholarship(db, name="Marie Curie Fellowship", slug="marie-curie")
    await _scholarship(db, name="Rhodes Scholarship", slug="rhodes")
    response = await client.get(
        "/api/v1/internal/admin/scholarships", params={"q": "curie"}, headers=AUTH
    )
    assert [row["name"] for row in response.json()["data"]] == ["Marie Curie Fellowship"]


async def test_a_percent_in_q_is_treated_literally_not_as_a_wildcard(db, client) -> None:
    await _scholarship(db, name="100% Tuition Award", slug="hundred-percent")
    await _scholarship(db, name="Unrelated Award", slug="unrelated")
    response = await client.get(
        "/api/v1/internal/admin/scholarships", params={"q": "100%"}, headers=AUTH
    )
    assert [row["name"] for row in response.json()["data"]] == ["100% Tuition Award"]


async def test_lifecycle_state_filter(db, client) -> None:
    await _scholarship(db, name="Needs Review Award", slug="needs-review-award")
    await _scholarship(
        db, name="Withdrawn Award", slug="withdrawn-award-2", lifecycle_state=RecordState.withdrawn
    )
    response = await client.get(
        "/api/v1/internal/admin/scholarships",
        params={"lifecycle_state": "withdrawn"},
        headers=AUTH,
    )
    body = response.json()
    assert body["total"] == 1
    assert body["data"][0]["name"] == "Withdrawn Award"


async def test_provider_id_filter(db, client) -> None:
    scholarship = await _scholarship(db, name="Award A", slug="award-a-filter")
    other_provider = Provider(name="Other University", approved_domains=["other.test"])
    db.add(other_provider)
    await db.flush()
    other = Scholarship(
        provider_id=other_provider.provider_id,
        slug="award-b-filter",
        name="Award B",
        official_home_url="https://example.test/award-b",
        lifecycle_state=RecordState.needs_review,
    )
    db.add(other)
    await db.commit()

    response = await client.get(
        "/api/v1/internal/admin/scholarships",
        params={"provider_id": str(other_provider.provider_id)},
        headers=AUTH,
    )
    body = response.json()
    assert body["total"] == 1
    assert body["data"][0]["scholarship_id"] == str(other.scholarship_id)
    assert scholarship.scholarship_id != other.scholarship_id


async def test_limit_caps_the_page_but_total_counts_every_match(db, client) -> None:
    for i in range(3):
        await _scholarship(db, name=f"Bulk Award {i}", slug=f"bulk-award-{i}")
    response = await client.get(
        "/api/v1/internal/admin/scholarships", params={"limit": 2}, headers=AUTH
    )
    body = response.json()
    assert len(body["data"]) == 2
    assert body["total"] == 3


async def test_public_status_filter_matches_the_stored_value(db, client) -> None:
    scholarship = await _scholarship(db, name="Open Award", slug="open-award")
    await client.post(
        f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/publish",
        json=CYCLE,
        headers=AUTH,
    )
    matching = await client.get(
        "/api/v1/internal/admin/scholarships",
        params={"public_status": "open_verified"},
        headers=AUTH,
    )
    assert matching.json()["total"] == 1
    not_matching = await client.get(
        "/api/v1/internal/admin/scholarships",
        params={"public_status": "status_unknown"},
        headers=AUTH,
    )
    assert not_matching.json()["total"] == 0


async def test_evaluated_public_status_reflects_a_deadline_the_stored_value_has_not_caught_up_to(
    db, client
) -> None:
    """A cycle published `open_verified` with a long-past date-only deadline:
    the stored column still says open (nothing has swept it), but the
    evaluated status must show what is actually true right now."""
    scholarship = await _scholarship(db, name="Expired Award", slug="expired-award")
    await client.post(
        f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/publish",
        json={
            **CYCLE,
            "deadline_at": "2020-01-01T00:00:00",
            "deadline_precision": "date",
        },
        headers=AUTH,
    )
    response = await client.get(
        "/api/v1/internal/admin/scholarships", params={"q": "Expired Award"}, headers=AUTH
    )
    cycle = response.json()["data"][0]["cycles"][0]
    assert cycle["public_status"] == "open_verified"
    assert cycle["evaluated_public_status"] == "status_unknown"
