"""Bulk review decisions - a reviewer working through a backlog one at a
time was the whole bottleneck this session's manual verification kept
hitting. One bad item in a batch must not cost the other nine."""

from __future__ import annotations

from sqlalchemy import select

from app.api.ingestion_schemas import FeedRecord
from app.domain.models import Discovery, Provider, ReviewTask, Source
from app.infra.ingestion import import_feed_records
from tests.conftest import requires_db

pytestmark = requires_db

AUTH = {"X-Service-Token": "internal-service-token"}


async def _open_task(db, *, slug_hint: str) -> tuple[ReviewTask, Provider]:
    source = Source(
        name="ScholarshipRegion",
        source_type="aggregator",
        authority_grade="C",
        approved_domains=["example.test"],
        active=True,
    )
    db.add(source)
    await db.commit()
    provider = Provider(name=f"Provider {slug_hint}", approved_domains=["example.test"])
    db.add(provider)
    await db.flush()
    await import_feed_records(
        db,
        [
            FeedRecord(
                source_id=source.source_id,
                url=f"https://example.test/{slug_hint}",
                title=f"Award {slug_hint}",
                excerpt="An award",
            )
        ],
    )
    # Not ordered by created_at: within one test transaction, Postgres's
    # now() is stable for the whole transaction, so two discoveries created
    # here could tie on timestamp. raw_title is unique per call instead.
    discovery = await db.scalar(
        select(Discovery).where(Discovery.raw_title == f"Award {slug_hint}")
    )
    task = ReviewTask(discovery_id=discovery.discovery_id, reason="new_candidate")
    db.add(task)
    await db.commit()
    return task, provider


def _approve_item(task_id, provider_id, slug: str) -> dict:
    return {
        "review_task_id": str(task_id),
        "decision": "approve",
        "provider_id": str(provider_id),
        "canonical_name": f"Award {slug}",
        "official_home_url": "https://example.test/award",
        "slug": slug,
        "award_type": "scholarship",
        "reason": "Official evidence checked",
    }


async def test_bulk_decision_requires_authentication(client) -> None:
    response = await client.post(
        "/api/v1/internal/admin/reviews/bulk-decision", json={"decisions": []}
    )
    assert response.status_code == 401


async def test_more_than_ten_items_is_refused(client) -> None:
    decisions = [
        {
            "review_task_id": f"01a06530-b2ef-7617-b74e-c22c6e40{i:04d}",
            "decision": "reject",
            "reason": "x",
        }
        for i in range(11)
    ]
    response = await client.post(
        "/api/v1/internal/admin/reviews/bulk-decision", json={"decisions": decisions}, headers=AUTH
    )
    assert response.status_code == 422


async def test_a_batch_of_approvals_and_rejections_all_apply(db, client) -> None:
    task_a, provider_a = await _open_task(db, slug_hint="a")
    task_b, provider_b = await _open_task(db, slug_hint="b")

    response = await client.post(
        "/api/v1/internal/admin/reviews/bulk-decision",
        json={
            "decisions": [
                _approve_item(task_a.review_task_id, provider_a.provider_id, "award-a"),
                {
                    "review_task_id": str(task_b.review_task_id),
                    "decision": "reject",
                    "reason": "No official source",
                },
            ]
        },
        headers=AUTH,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert all(row["success"] for row in body["results"])
    approved, rejected = body["results"]
    assert approved["scholarship_id"] is not None
    assert rejected["scholarship_id"] is None

    await db.refresh(task_a)
    await db.refresh(task_b)
    assert task_a.state == "resolved"
    assert task_b.state == "resolved"


async def test_one_bad_item_does_not_block_the_rest_of_the_batch(db, client) -> None:
    task_a, provider_a = await _open_task(db, slug_hint="good")
    task_b, _provider_b = await _open_task(db, slug_hint="bad")

    response = await client.post(
        "/api/v1/internal/admin/reviews/bulk-decision",
        json={
            "decisions": [
                _approve_item(task_a.review_task_id, provider_a.provider_id, "award-good"),
                {
                    # Missing provider_id/slug/official_home_url/award_type entirely.
                    "review_task_id": str(task_b.review_task_id),
                    "decision": "approve",
                    "reason": "Incomplete on purpose",
                },
            ]
        },
        headers=AUTH,
    )
    assert response.status_code == 200, response.text
    good, bad = response.json()["results"]
    assert good["success"] is True
    assert good["scholarship_id"] is not None
    assert bad["success"] is False
    assert bad["error"]

    await db.refresh(task_a)
    await db.refresh(task_b)
    assert task_a.state == "resolved"
    assert task_b.state == "open", "a failed item must not resolve the task it failed on"


async def test_an_unknown_review_task_id_is_reported_per_item(client) -> None:
    response = await client.post(
        "/api/v1/internal/admin/reviews/bulk-decision",
        json={
            "decisions": [
                {
                    "review_task_id": "01a06530-b2ef-7617-b74e-c22c6e4053fa",
                    "decision": "reject",
                    "reason": "No official source",
                }
            ]
        },
        headers=AUTH,
    )
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["success"] is False
    assert "not found" in result["error"].lower()
