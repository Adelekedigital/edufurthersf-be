"""Publishing an approved scholarship: the gate between approved and public."""

from __future__ import annotations

from sqlalchemy import select

from app.domain.models import AuditLog, OutboxEvent, Provider, RecordState, Scholarship
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

SEARCH = {
    "origin_country": "NG",
    "program_level": "masters",
    "field": "public_health",
    "target_countries": ["CA"],
}


async def _approved_scholarship(db, *, slug: str = "award-a") -> Scholarship:
    """A record at exactly the state decide_review leaves it: approved, unpublished."""
    provider = Provider(name="Example University", approved_domains=["example.test"])
    db.add(provider)
    await db.flush()
    scholarship = Scholarship(
        provider_id=provider.provider_id,
        slug=slug,
        name="Award A",
        official_home_url="https://example.test/award",
        award_type="scholarship",
        lifecycle_state=RecordState.needs_review,
    )
    db.add(scholarship)
    await db.commit()
    return scholarship


async def test_publishing_requires_authentication(db, client) -> None:
    scholarship = await _approved_scholarship(db)
    response = await client.post(
        f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/publish", json=CYCLE
    )
    assert response.status_code == 401


async def test_publish_makes_the_scholarship_findable(db, client) -> None:
    scholarship = await _approved_scholarship(db)
    response = await client.post(
        f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/publish",
        json=CYCLE,
        headers=AUTH,
    )
    assert response.status_code == 200, response.text
    assert response.json()["lifecycle_state"] == "published"

    await db.refresh(scholarship)
    assert scholarship.lifecycle_state == RecordState.published

    results = (await client.post("/api/v1/search", json=SEARCH)).json()["data"]
    assert [row["name"] for row in results] == ["Award A"]


async def test_publish_records_an_audit_entry_and_analytics_event(db, client) -> None:
    scholarship = await _approved_scholarship(db)
    await client.post(
        f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/publish",
        json=CYCLE,
        headers=AUTH,
    )
    entry = await db.scalar(select(AuditLog))
    assert entry.action == "scholarship.published"
    assert entry.target_id == scholarship.scholarship_id

    event = await db.scalar(
        select(OutboxEvent).where(OutboxEvent.event_type == "scholarship_published")
    )
    assert event is not None


async def test_an_unsupported_destination_is_refused(db, client) -> None:
    scholarship = await _approved_scholarship(db)
    response = await client.post(
        f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/publish",
        json={**CYCLE, "destinations": ["NG"]},
        headers=AUTH,
    )
    assert response.status_code == 422
    assert "coverage" in response.text


async def test_restricted_origin_mode_without_origins_is_refused(db, client) -> None:
    scholarship = await _approved_scholarship(db)
    response = await client.post(
        f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/publish",
        json={**CYCLE, "origin_mode": "restricted", "origins": []},
        headers=AUTH,
    )
    assert response.status_code == 422


async def test_an_unknown_degree_level_is_refused(db, client) -> None:
    scholarship = await _approved_scholarship(db)
    response = await client.post(
        f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/publish",
        json={**CYCLE, "levels": ["postdoc"]},
        headers=AUTH,
    )
    assert response.status_code == 422


async def test_a_duplicate_cycle_key_is_a_conflict(db, client) -> None:
    scholarship = await _approved_scholarship(db)
    url = f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/publish"
    assert (await client.post(url, json=CYCLE, headers=AUTH)).status_code == 200
    again = await client.post(url, json=CYCLE, headers=AUTH)
    assert again.status_code == 409


async def test_publishing_a_withdrawn_scholarship_is_a_conflict(db, client) -> None:
    scholarship = await _approved_scholarship(db)
    scholarship.lifecycle_state = RecordState.withdrawn
    await db.commit()
    response = await client.post(
        f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/publish",
        json=CYCLE,
        headers=AUTH,
    )
    assert response.status_code == 409


async def test_publishing_an_unknown_scholarship_is_a_404(client) -> None:
    response = await client.post(
        "/api/v1/internal/admin/scholarships/01a06530-b2ef-7617-b74e-c22c6e4053fa/publish",
        json=CYCLE,
        headers=AUTH,
    )
    assert response.status_code == 404


async def test_an_eligibility_note_surfaces_as_its_own_field_not_a_caveat(db, client) -> None:
    """origin_mode/origins cannot represent every real restriction (an
    exclude-one rule, an immigration status, a demographic restriction) -
    eligibility_note is what is left once that honest call has been made. It
    is a distinct field, not folded into generic matching/freshness caveats,
    so a frontend can render it as its own label rather than lose it inside
    a caveats list meant for "this data needs re-verification" warnings."""
    scholarship = await _approved_scholarship(db)
    response = await client.post(
        f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/publish",
        json={**CYCLE, "eligibility_note": "Not open to UK nationals or home-fee-status students."},
        headers=AUTH,
    )
    assert response.status_code == 200, response.text

    results = (await client.post("/api/v1/search", json=SEARCH)).json()["data"]
    assert results[0]["eligibility_note"] == "Not open to UK nationals or home-fee-status students."
    assert results[0]["caveats"] == []

    detail = (await client.get(f"/api/v1/scholarships/{scholarship.scholarship_id}")).json()
    assert detail["eligibility_note"] == "Not open to UK nationals or home-fee-status students."
    assert detail["caveats"] == []


async def test_a_second_cycle_can_be_added_to_an_already_published_scholarship(db, client) -> None:
    """A new intake is not a reason to unpublish the last one."""
    scholarship = await _approved_scholarship(db)
    url = f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/publish"
    assert (await client.post(url, json=CYCLE, headers=AUTH)).status_code == 200
    second = await client.post(
        url, json={**CYCLE, "provider_cycle_key": "2028-intake"}, headers=AUTH
    )
    assert second.status_code == 200
    await db.refresh(scholarship)
    assert scholarship.lifecycle_state == RecordState.published
