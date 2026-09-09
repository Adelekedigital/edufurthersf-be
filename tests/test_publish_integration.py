"""Publishing an approved scholarship: the gate between approved and public."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.domain.models import (
    AuditLog,
    OutboxEvent,
    Provider,
    RecordState,
    Scholarship,
    ScholarshipCycle,
)
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
    "fields": ["health"],
    "evidence_fresh": True,
}

SEARCH = {
    "origin_country": "NG",
    "program_levels": ["masters"],
    "field": "health_and_medical_sciences",
    "target_countries": ["CA"],
}


async def _approved_scholarship(
    db, *, slug: str = "award-a", provider_country: str | None = None
) -> Scholarship:
    """A record at exactly the state decide_review leaves it: approved, unpublished."""
    provider = Provider(
        name="Example University", approved_domains=["example.test"], country=provider_country
    )
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


async def test_expected_reopen_month_produces_likely_to_open_status_detail(db, client) -> None:
    """The month is dynamic (this-month, not a fixed one) so the assertion
    holds regardless of when the suite actually runs."""
    scholarship = await _approved_scholarship(db, slug="reopen-soon")
    cycle = {
        **CYCLE,
        "public_status": "expected_to_reopen",
        "expected_reopen_month": datetime.now(UTC).month,
    }
    response = await client.post(
        f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/publish",
        json=cycle,
        headers=AUTH,
    )
    assert response.status_code == 200, response.text

    results = (await client.post("/api/v1/search", json=SEARCH)).json()["data"]
    assert [row["status_detail"] for row in results] == ["likely_to_open"]


async def test_no_expected_reopen_month_is_likely_to_open(db, client) -> None:
    scholarship = await _approved_scholarship(db, slug="reopen-unknown")
    cycle = {**CYCLE, "public_status": "expected_to_reopen"}
    await client.post(
        f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/publish",
        json=cycle,
        headers=AUTH,
    )
    results = (await client.post("/api/v1/search", json=SEARCH)).json()["data"]
    assert [row["status_detail"] for row in results] == ["likely_to_open"]


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


async def test_a_result_carries_its_own_destination_not_the_search_filter(db, client) -> None:
    """A search can target several countries at once; which one(s) a given
    award actually covers is a fact about the award, not something a
    frontend should infer from the query it ran (e.g. always showing the
    first selected destination)."""
    scholarship = await _approved_scholarship(db)
    response = await client.post(
        f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/publish",
        json=CYCLE,
        headers=AUTH,
    )
    assert response.status_code == 200, response.text

    # GB listed first, deliberately - the award's real destination is CA. If
    # this ever regressed back to reading target_countries[0] instead of the
    # award's own facts, GB-first would catch it; CA-first would not.
    multi_country_search = {**SEARCH, "target_countries": ["GB", "CA"]}
    results = (await client.post("/api/v1/search", json=multi_country_search)).json()["data"]
    assert results[0]["destinations"] == ["CA"]

    detail = (await client.get(f"/api/v1/scholarships/{scholarship.scholarship_id}")).json()
    assert detail["destinations"] == ["CA"]


async def test_search_result_exposes_deadline_and_degree_levels(db, client) -> None:
    """These are already computed internally for status/status_detail - the
    search card needs them surfaced directly rather than reverse-engineered
    from status_detail copy."""
    scholarship = await _approved_scholarship(db)
    response = await client.post(
        f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/publish",
        json={
            **CYCLE,
            "deadline_at": "2026-12-31T00:00:00Z",
            "deadline_precision": "date",
        },
        headers=AUTH,
    )
    assert response.status_code == 200, response.text

    result = (await client.post("/api/v1/search", json=SEARCH)).json()["data"][0]
    assert result["deadline_at"].startswith("2026-12-31")
    assert result["deadline_precision"] == "date"
    assert result["degree_levels"] == ["masters"]
    assert result["expected_reopen_month"] is None

    # The detail endpoint carries the same fields, not just search - a
    # frontend building a detail page shouldn't need to parse `facts` for
    # data the search card already gets as first-class fields.
    detail = (await client.get(f"/api/v1/scholarships/{scholarship.scholarship_id}")).json()
    assert detail["deadline_at"].startswith("2026-12-31")
    assert detail["deadline_precision"] == "date"
    assert detail["degree_levels"] == ["masters"]


async def test_a_malformed_deadline_at_nulls_both_deadline_fields(db, client) -> None:
    scholarship = await _approved_scholarship(db)
    response = await client.post(
        f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/publish",
        json={**CYCLE, "deadline_at": "2026-12-31T00:00:00Z", "deadline_precision": "date"},
        headers=AUTH,
    )
    assert response.status_code == 200, response.text

    cycle = await db.scalar(select(ScholarshipCycle))
    cycle.facts = {**cycle.facts, "deadline_at": "not-a-real-date"}
    db.add(cycle)
    await db.commit()

    result = (await client.post("/api/v1/search", json=SEARCH)).json()["data"][0]
    assert result["deadline_at"] is None
    assert result["deadline_precision"] is None


async def test_search_result_exposes_expected_reopen_month_not_a_deadline(db, client) -> None:
    """A `expected_to_reopen` cycle has no deadline at all - only a cyclic
    month, never a fabricated year."""
    scholarship = await _approved_scholarship(db)
    response = await client.post(
        f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/publish",
        json={
            **CYCLE,
            "public_status": "expected_to_reopen",
            "expected_reopen_month": 2,
        },
        headers=AUTH,
    )
    assert response.status_code == 200, response.text

    result = (await client.post("/api/v1/search", json=SEARCH)).json()["data"][0]
    assert result["expected_reopen_month"] == 2
    assert result["deadline_at"] is None
    assert result["deadline_precision"] is None


async def test_funding_type_is_distinct_from_award_type(db, client) -> None:
    """award_type is what kind of instrument this is (scholarship/grant/...);
    funding_type is how much of the cost it covers - the two vary
    independently, so neither substitutes for the other."""
    scholarship = await _approved_scholarship(db)
    response = await client.post(
        f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/publish",
        json={**CYCLE, "funding_type": "fully_funded"},
        headers=AUTH,
    )
    assert response.status_code == 200, response.text

    result = (await client.post("/api/v1/search", json=SEARCH)).json()["data"][0]
    assert result["funding_type"] == "fully_funded"
    assert result["award_type"] == "scholarship"

    detail = (await client.get(f"/api/v1/scholarships/{scholarship.scholarship_id}")).json()
    assert detail["funding_type"] == "fully_funded"


async def test_an_unsupported_funding_type_is_a_422(db, client) -> None:
    scholarship = await _approved_scholarship(db)
    response = await client.post(
        f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/publish",
        json={**CYCLE, "funding_type": "not_a_real_funding_type"},
        headers=AUTH,
    )
    assert response.status_code == 422


async def test_funding_type_is_optional_and_absent_by_default(db, client) -> None:
    """No taxonomy-forcing: a cycle published without funding evidence
    reports null, never a guessed default."""
    scholarship = await _approved_scholarship(db)
    response = await client.post(
        f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/publish",
        json=CYCLE,
        headers=AUTH,
    )
    assert response.status_code == 200, response.text

    result = (await client.post("/api/v1/search", json=SEARCH)).json()["data"][0]
    assert result["funding_type"] is None


async def test_provider_country_is_the_providers_own_fact_not_the_study_destination(
    db, client
) -> None:
    """A UK-based foundation funding study in Canada should show provider
    "GB" alongside destinations ["CA"] - the two are unrelated facts, and
    neither substitutes for the other."""
    scholarship = await _approved_scholarship(db, provider_country="GB")
    response = await client.post(
        f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/publish",
        json=CYCLE,
        headers=AUTH,
    )
    assert response.status_code == 200, response.text

    result = (await client.post("/api/v1/search", json=SEARCH)).json()["data"][0]
    assert result["provider_country"] == "GB"
    assert result["destinations"] == ["CA"]

    detail = (await client.get(f"/api/v1/scholarships/{scholarship.scholarship_id}")).json()
    assert detail["provider_country"] == "GB"


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
