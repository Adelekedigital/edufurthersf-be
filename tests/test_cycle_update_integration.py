"""Correcting an already-published cycle in place.

Publishing is the gate between approved and public; this is what happens
after, when a reviewer finds the live record says something the provider's
page does not. The rules that matter here are that a correction cannot write
anything a publish would have refused, and that it stays traceable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.domain.models import (
    AuditLog,
    Provider,
    PublicStatus,
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
    "origin_mode": "restricted",
    "origins": ["NG", "TR"],
    "field_mode": "restricted",
    "fields": ["health"],
    "evidence_fresh": True,
    "eligibility_note": "Open to international students.",
}


async def _published(db, client, *, slug: str = "award-a") -> tuple[Scholarship, ScholarshipCycle]:
    """A record at exactly the state a publish leaves it: live, one cycle."""
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

    response = await client.post(
        f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/publish",
        json=CYCLE,
        headers=AUTH,
    )
    assert response.status_code == 200
    cycle = await db.scalar(
        select(ScholarshipCycle).where(
            ScholarshipCycle.scholarship_id == scholarship.scholarship_id
        )
    )
    assert cycle is not None
    return scholarship, cycle


def _url(scholarship: Scholarship, cycle: ScholarshipCycle) -> str:
    return (
        f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}"
        f"/cycles/{cycle.cycle_id}"
    )


async def test_updating_requires_authentication(db, client) -> None:
    scholarship, cycle = await _published(db, client)
    response = await client.patch(_url(scholarship, cycle), json={"levels": ["doctorate"]})
    assert response.status_code == 401


async def test_an_unknown_cycle_is_a_404(db, client) -> None:
    scholarship, _ = await _published(db, client)
    missing = "00000000-0000-0000-0000-000000000000"
    response = await client.patch(
        f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/cycles/{missing}",
        json={"levels": ["doctorate"]},
        headers=AUTH,
    )
    assert response.status_code == 404


async def test_an_unknown_scholarship_is_a_404(db, client) -> None:
    _, cycle = await _published(db, client)
    missing = "00000000-0000-0000-0000-000000000000"
    response = await client.patch(
        f"/api/v1/internal/admin/scholarships/{missing}/cycles/{cycle.cycle_id}",
        json={"levels": ["doctorate"]},
        headers=AUTH,
    )
    assert response.status_code == 404


async def test_an_unparseable_stored_deadline_is_refused(db, client) -> None:
    """A correction must not quietly widen a cycle's window.

    Reconstructing the stored facts is how an edit re-validates the parts it
    was not sent. If a deadline written by hand or by an older shape cannot
    be read back, dropping it would silently remove the cutoff - so it is
    surfaced instead, even though the caller never touched that field.
    """
    scholarship, cycle = await _published(db, client)
    cycle.facts = dict(cycle.facts, deadline_at="not-a-timestamp")
    await db.commit()

    response = await client.patch(
        _url(scholarship, cycle), json={"levels": ["doctorate"]}, headers=AUTH
    )
    assert response.status_code == 422
    assert "deadline_at" in response.json()["detail"]

    await db.refresh(cycle)
    assert cycle.facts["levels"] == ["masters"]


async def test_a_cycle_belonging_to_another_scholarship_is_a_404(db, client) -> None:
    """Scoped to its parent: the wrong parent is a mistake, not a silent edit."""
    _, cycle = await _published(db, client, slug="award-a")
    other, _ = await _published(db, client, slug="award-b")
    response = await client.patch(
        f"/api/v1/internal/admin/scholarships/{other.scholarship_id}/cycles/{cycle.cycle_id}",
        json={"levels": ["doctorate"]},
        headers=AUTH,
    )
    assert response.status_code == 404


async def test_an_empty_body_is_refused(db, client) -> None:
    scholarship, cycle = await _published(db, client)
    response = await client.patch(_url(scholarship, cycle), json={}, headers=AUTH)
    assert response.status_code == 422


async def test_only_the_fields_sent_are_changed(db, client) -> None:
    """The point of a partial update: fixing a deadline must not clear the rest."""
    scholarship, cycle = await _published(db, client)
    deadline = datetime.now(UTC) + timedelta(days=30)

    response = await client.patch(
        _url(scholarship, cycle),
        json={"deadline_at": deadline.isoformat()},
        headers=AUTH,
    )
    assert response.status_code == 200

    await db.refresh(cycle)
    assert cycle.facts["deadline_at"].startswith(deadline.isoformat()[:19])
    # Everything not sent survived.
    assert cycle.facts["destinations"] == ["CA"]
    assert cycle.facts["levels"] == ["masters"]
    assert cycle.facts["origins"] == ["NG", "TR"]
    assert cycle.facts["eligibility_note"] == "Open to international students."
    assert cycle.provider_cycle_key == "2027-intake"


async def test_a_nullable_field_can_be_cleared(db, client) -> None:
    """Sending null really removes it - distinct from leaving it out."""
    scholarship, cycle = await _published(db, client)
    response = await client.patch(
        _url(scholarship, cycle), json={"eligibility_note": None}, headers=AUTH
    )
    assert response.status_code == 200

    await db.refresh(cycle)
    assert "eligibility_note" not in cycle.facts
    assert cycle.facts["destinations"] == ["CA"]


async def test_columns_and_facts_can_change_together(db, client) -> None:
    scholarship, cycle = await _published(db, client)
    valid_until = datetime.now(UTC) + timedelta(days=90)

    response = await client.patch(
        _url(scholarship, cycle),
        json={
            "public_status": "expected_to_reopen",
            "status_valid_until": valid_until.isoformat(),
            "official_cycle_url": "https://example.test/apply-2028",
            "destinations": ["GB"],
            "expected_reopen_month": 9,
        },
        headers=AUTH,
    )
    assert response.status_code == 200
    assert response.json()["public_status"] == "expected_to_reopen"

    await db.refresh(cycle)
    assert cycle.public_status is PublicStatus.expected_to_reopen
    assert cycle.official_cycle_url == "https://example.test/apply-2028"
    assert cycle.facts["destinations"] == ["GB"]
    assert cycle.facts["expected_reopen_month"] == 9


async def test_an_unsupported_destination_is_refused(db, client) -> None:
    """An edit goes through the same vocabulary gate a publish does."""
    scholarship, cycle = await _published(db, client)
    response = await client.patch(
        _url(scholarship, cycle), json={"destinations": ["ZZ"]}, headers=AUTH
    )
    assert response.status_code == 422

    await db.refresh(cycle)
    assert cycle.facts["destinations"] == ["CA"]


async def test_restricting_origins_without_a_list_is_refused(db, client) -> None:
    """The cross-field rule holds against the stored value, not just the sent one."""
    scholarship, cycle = await _published(db, client)
    response = await client.patch(
        _url(scholarship, cycle),
        json={"origin_mode": "restricted", "origins": []},
        headers=AUTH,
    )
    assert response.status_code == 422


async def test_widening_origins_keeps_the_stored_mode_valid(db, client) -> None:
    """Changing only the list is validated against the mode already stored."""
    scholarship, cycle = await _published(db, client)
    response = await client.patch(_url(scholarship, cycle), json={"origins": ["SA"]}, headers=AUTH)
    assert response.status_code == 200

    await db.refresh(cycle)
    assert cycle.facts["origin_mode"] == "restricted"
    assert cycle.facts["origins"] == ["SA"]


async def test_renaming_onto_an_existing_cycle_key_is_a_conflict(db, client) -> None:
    scholarship, cycle = await _published(db, client)
    second = dict(CYCLE, provider_cycle_key="2028-intake")
    created = await client.post(
        f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/publish",
        json=second,
        headers=AUTH,
    )
    assert created.status_code == 200

    response = await client.patch(
        _url(scholarship, cycle), json={"provider_cycle_key": "2028-intake"}, headers=AUTH
    )
    assert response.status_code == 409

    await db.refresh(cycle)
    assert cycle.provider_cycle_key == "2027-intake"


async def test_a_cycle_key_can_be_renamed_to_a_free_one(db, client) -> None:
    """Correcting a mistyped key is the reason the identity fields are editable."""
    scholarship, cycle = await _published(db, client)
    response = await client.patch(
        _url(scholarship, cycle),
        json={"provider_cycle_key": "2027-28-intake", "applicant_segment": "eu"},
        headers=AUTH,
    )
    assert response.status_code == 200

    await db.refresh(cycle)
    assert cycle.provider_cycle_key == "2027-28-intake"
    assert cycle.applicant_segment == "eu"
    # A rename is not a republish: still one cycle, same id.
    remaining = list(
        await db.scalars(
            select(ScholarshipCycle).where(
                ScholarshipCycle.scholarship_id == scholarship.scholarship_id
            )
        )
    )
    assert [item.cycle_id for item in remaining] == [cycle.cycle_id]


async def test_a_cycle_can_keep_its_own_key(db, client) -> None:
    """Resending the unchanged key must not collide with the row it belongs to."""
    scholarship, cycle = await _published(db, client)
    response = await client.patch(
        _url(scholarship, cycle),
        json={"provider_cycle_key": "2027-intake", "levels": ["doctorate"]},
        headers=AUTH,
    )
    assert response.status_code == 200

    await db.refresh(cycle)
    assert cycle.facts["levels"] == ["doctorate"]


async def test_updating_a_withdrawn_scholarship_is_a_conflict(db, client) -> None:
    """Editing what was pulled from public results is not a way to bring it back."""
    scholarship, cycle = await _published(db, client)
    withdrawn = await client.post(
        f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/withdraw",
        json={"reason": "Provider page is gone."},
        headers=AUTH,
    )
    assert withdrawn.status_code == 200

    response = await client.patch(
        _url(scholarship, cycle), json={"levels": ["doctorate"]}, headers=AUTH
    )
    assert response.status_code == 409


async def test_updating_records_an_audit_entry_naming_what_changed(db, client) -> None:
    scholarship, cycle = await _published(db, client)
    await client.patch(
        _url(scholarship, cycle),
        json={"levels": ["doctorate"], "evidence_fresh": False},
        headers=AUTH,
    )

    entry = await db.scalar(
        select(AuditLog).where(AuditLog.action == "scholarship.cycle_updated")
    )
    assert entry is not None
    assert entry.target_id == scholarship.scholarship_id
    assert entry.actor == "internal_service"
    # A live listing changed under its users: which fields moved is the thing
    # an audit needs, and it should not require diffing two snapshots.
    assert entry.context["changed_fields"] == ["evidence_fresh", "levels"]
    assert entry.context["cycle_id"] == str(cycle.cycle_id)


async def test_the_admin_list_reflects_the_correction(db, client) -> None:
    """The read path recomputes from the stored values, so an edit is visible."""
    scholarship, cycle = await _published(db, client)
    await client.patch(_url(scholarship, cycle), json={"levels": ["doctorate"]}, headers=AUTH)

    listed = await client.get("/api/v1/internal/admin/scholarships", headers=AUTH)
    assert listed.status_code == 200
    record = next(
        item
        for item in listed.json()["data"]
        if item["scholarship_id"] == str(scholarship.scholarship_id)
    )
    assert record["cycles"][0]["facts"]["levels"] == ["doctorate"]
