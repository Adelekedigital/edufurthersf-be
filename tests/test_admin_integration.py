"""The reviewer surface: work queue and immediate withdrawal."""

from __future__ import annotations

from sqlalchemy import select

from app.domain.models import (
    AuditLog,
    OutboxEvent,
    Provider,
    PublicStatus,
    RecordState,
    ReviewTask,
    Scholarship,
    ScholarshipCycle,
    Source,
)
from app.infra.ingestion import import_feed_records
from tests.conftest import requires_db
from tests.test_pipeline_integration import _record
from tests.test_search_integration import CONFIRMED_FACTS, SEARCH, _publish

pytestmark = requires_db

AUTH = {"X-Service-Token": "internal-service-token"}


async def test_the_review_queue_requires_authentication(client) -> None:
    assert (await client.get("/api/v1/internal/admin/reviews")).status_code == 401


async def test_the_queue_orders_by_priority_then_age(db, client) -> None:
    db.add(ReviewTask(reason="low_priority", priority=200))
    db.add(ReviewTask(reason="urgent", priority=10))
    db.add(ReviewTask(reason="already_done", priority=1, state="resolved"))
    await db.commit()

    body = (await client.get("/api/v1/internal/admin/reviews", headers=AUTH)).json()
    assert [task["reason"] for task in body["data"]] == ["urgent", "low_priority"]
    assert body["open_count"] == 2, "resolved work is not outstanding"


async def test_a_cycle_linked_task_surfaces_its_cycle_id(db, client) -> None:
    """A refresh_status/reverify_due-opened task (infra/freshness.py) has no
    discovery - cycle_id is what lets a reviewer (or a future frontend) tell
    which cycle it's about without parsing draft_recommendation by hand."""
    provider = Provider(name="Example University", approved_domains=["example.test"])
    db.add(provider)
    await db.flush()
    scholarship = Scholarship(
        provider_id=provider.provider_id,
        slug="award-cycle-link",
        name="Award",
        official_home_url="https://example.test/award",
        award_type="scholarship",
        lifecycle_state=RecordState.published,
    )
    db.add(scholarship)
    await db.flush()
    cycle = ScholarshipCycle(
        scholarship_id=scholarship.scholarship_id,
        provider_cycle_key="award-cycle-link-2026",
        official_cycle_url="https://example.test/award/apply",
        public_status=PublicStatus.open_verified,
        facts={},
    )
    db.add(cycle)
    await db.flush()
    db.add(ReviewTask(cycle_id=cycle.cycle_id, reason="reverify_content_changed"))
    await db.commit()

    body = (await client.get("/api/v1/internal/admin/reviews", headers=AUTH)).json()
    assert body["data"][0]["cycle_id"] == str(cycle.cycle_id)
    assert body["data"][0]["discovery_id"] is None


async def test_the_queue_carries_enough_to_actually_review_something(db, client) -> None:
    """A bare title is not enough to verify a claim or tell two similarly
    titled candidates apart; the queue must carry the excerpt and the source
    URL too."""
    source = Source(
        name="ScholarshipRegion",
        source_type="aggregator",
        authority_grade="C",
        approved_domains=["example.test"],
        active=True,
    )
    db.add(source)
    await db.commit()
    await import_feed_records(
        db, [_record(source.source_id, "https://example.test/award", "Real Award")]
    )
    await client.post("/api/v1/internal/admin/jobs/run-due", headers=AUTH)

    body = (await client.get("/api/v1/internal/admin/reviews", headers=AUTH)).json()
    assert len(body["data"]) == 1
    task = body["data"][0]
    assert task["raw_title"] == "Real Award"
    assert task["raw_excerpt"] == "An award"
    assert task["source_url"] == "https://example.test/award"


async def test_the_queue_can_show_resolved_tasks(db, client) -> None:
    db.add(ReviewTask(reason="already_done", priority=1, state="resolved"))
    await db.commit()
    body = (await client.get("/api/v1/internal/admin/reviews?state=resolved", headers=AUTH)).json()
    assert [task["reason"] for task in body["data"]] == ["already_done"]


async def test_withdrawal_removes_a_record_from_search_immediately(db, client) -> None:
    """A misleading record must disappear without waiting for a sweep."""
    await _publish(db, slug="bad", facts=CONFIRMED_FACTS, status=PublicStatus.open_verified)
    scholarship = await db.scalar(select(Scholarship))
    assert (await client.post("/api/v1/search", json=SEARCH)).json()["data"]

    response = await client.post(
        f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/withdraw",
        json={"reason": "Provider confirmed the award was never open"},
        headers=AUTH,
    )
    assert response.status_code == 200, response.text
    assert response.json()["withdrawn_cycles"] == 1

    assert (await client.post("/api/v1/search", json=SEARCH)).json()["data"] == []
    await db.refresh(scholarship)
    assert scholarship.lifecycle_state == RecordState.withdrawn


async def test_withdrawal_is_audited_and_announced(db, client) -> None:
    await _publish(db, slug="bad", facts=CONFIRMED_FACTS, status=PublicStatus.open_verified)
    scholarship = await db.scalar(select(Scholarship))
    await client.post(
        f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/withdraw",
        json={"reason": "Conflicting official facts"},
        headers=AUTH,
    )
    entry = await db.scalar(select(AuditLog))
    assert entry.action == "scholarship.withdrawn"
    assert entry.target_id == scholarship.scholarship_id
    assert entry.reason == "Conflicting official facts"

    event = await db.scalar(
        select(OutboxEvent).where(OutboxEvent.event_type == "scholarship_withdrawn")
    )
    assert event is not None


async def test_withdrawing_twice_is_refused(db, client) -> None:
    await _publish(db, slug="bad", facts=CONFIRMED_FACTS, status=PublicStatus.open_verified)
    scholarship = await db.scalar(select(Scholarship))
    url = f"/api/v1/internal/admin/scholarships/{scholarship.scholarship_id}/withdraw"
    assert (await client.post(url, json={"reason": "first"}, headers=AUTH)).status_code == 200
    assert (await client.post(url, json={"reason": "again"}, headers=AUTH)).status_code == 409


async def test_withdrawing_an_unknown_record_is_a_404(client) -> None:
    response = await client.post(
        "/api/v1/internal/admin/scholarships/01a06530-b2ef-7617-b74e-c22c6e4053fa/withdraw",
        json={"reason": "does not exist"},
        headers=AUTH,
    )
    assert response.status_code == 404
