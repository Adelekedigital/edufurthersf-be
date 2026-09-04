"""The manual stopgap for jobs feed import creates but never delivers to QStash.

import_feed_records writes ProcessingJob rows directly - it never publishes
them to QStash, so nothing else in the deployed app executes them. This is
exactly what left 247 real discoveries with an empty review queue in
production: the rows existed, their link_canonical jobs did not."""

from __future__ import annotations

from sqlalchemy import select

from app.domain.models import ProcessingJob, ReviewTask, Source
from app.infra.ingestion import import_feed_records
from tests.conftest import requires_db
from tests.test_pipeline_integration import _record

pytestmark = requires_db

AUTH = {"X-Service-Token": "internal-service-token"}


async def _source(db) -> Source:
    source = Source(
        name="ScholarshipRegion",
        source_type="aggregator",
        authority_grade="C",
        approved_domains=["example.test"],
        active=True,
    )
    db.add(source)
    await db.commit()
    return source


async def test_run_due_requires_authentication(client) -> None:
    assert (await client.post("/api/v1/internal/admin/jobs/run-due")).status_code == 401


async def test_import_alone_leaves_jobs_stuck_at_queued(db) -> None:
    """The exact bug found in production, reproduced directly: importing does
    not itself execute anything."""
    source = await _source(db)
    await import_feed_records(db, [_record(source.source_id, "https://example.test/a", "Award A")])
    states = {job.state for job in await db.scalars(select(ProcessingJob))}
    assert states == {"queued"}
    assert await db.scalar(select(ReviewTask)) is None


async def test_run_due_executes_jobs_import_left_stuck(db, client) -> None:
    source = await _source(db)
    await import_feed_records(
        db,
        [
            _record(source.source_id, "https://example.test/a", "Award A"),
            _record(source.source_id, "https://example.test/b", "Award B"),
        ],
    )
    # Two discoveries, two jobs each: normalize_discovery + link_canonical.
    assert len(list(await db.scalars(select(ProcessingJob)))) == 4

    response = await client.post("/api/v1/internal/admin/jobs/run-due", headers=AUTH)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {"completed": 4, "failed": 0, "remaining": 0}

    states = {job.state for job in await db.scalars(select(ProcessingJob))}
    assert states == {"completed"}
    tasks = list(await db.scalars(select(ReviewTask)))
    assert len(tasks) == 2, "each discovery's own link_canonical must have run"
    assert all(task.reason == "no_identity_candidate" for task in tasks)


async def test_run_due_is_safe_to_call_twice(db, client) -> None:
    source = await _source(db)
    await import_feed_records(db, [_record(source.source_id, "https://example.test/a", "Award A")])
    first = await client.post("/api/v1/internal/admin/jobs/run-due", headers=AUTH)
    assert first.json()["completed"] == 2

    second = await client.post("/api/v1/internal/admin/jobs/run-due", headers=AUTH)
    assert second.json() == {"completed": 0, "failed": 0, "remaining": 0}
    assert len(list(await db.scalars(select(ReviewTask)))) == 1, "not re-run, not duplicated"


async def test_run_due_respects_its_limit_and_reports_remaining(db, client) -> None:
    source = await _source(db)
    await import_feed_records(
        db,
        [
            _record(source.source_id, "https://example.test/a", "Award A"),
            _record(source.source_id, "https://example.test/b", "Award B"),
            _record(source.source_id, "https://example.test/c", "Award C"),
        ],
    )
    assert len(list(await db.scalars(select(ProcessingJob)))) == 6

    response = await client.post(
        "/api/v1/internal/admin/jobs/run-due", params={"limit": 2}, headers=AUTH
    )
    body = response.json()
    assert body["completed"] == 2
    assert body["remaining"] == 4
