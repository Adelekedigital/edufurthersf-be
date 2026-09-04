"""Closing the "jobs feed import never delivers" gap for real: each job import
creates is now published to QStash, so /internal/jobs actually gets a delivery
to execute instead of relying entirely on the manual run-due stopgap."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

import app.infra.ingestion as ingestion
from app.domain.models import ProcessingJob, Source
from app.infra.ingestion import import_feed_records
from tests.conftest import requires_db
from tests.test_pipeline_integration import _record

pytestmark = requires_db

DESTINATION = "https://finder.test/api/v1/internal/jobs"


class _FakePublisher:
    """Stands in for QStashPublisher: no real network call, just records what
    would have been sent."""

    calls: list[dict[str, Any]] = []
    fail_kinds: set[str] = set()

    def __init__(self, qstash_url: str, token: str) -> None:
        self.qstash_url = qstash_url
        self.token = token

    async def publish(
        self, destination: str, body: dict[str, Any], deduplication_id: str | None = None
    ) -> dict[str, Any]:
        _FakePublisher.calls.append(
            {"destination": destination, "body": body, "deduplication_id": deduplication_id}
        )
        if body["kind"] in _FakePublisher.fail_kinds:
            raise RuntimeError("QStash unreachable")
        return {"messageId": "fake"}


@pytest.fixture(autouse=True)
def _reset_fake_publisher():
    _FakePublisher.calls = []
    _FakePublisher.fail_kinds = set()
    yield
    _FakePublisher.calls = []
    _FakePublisher.fail_kinds = set()


@pytest.fixture
def qstash_configured(monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "qstash_token", "test-qstash-token", raising=False)
    monkeypatch.setattr(settings, "qstash_expected_destination", DESTINATION, raising=False)
    monkeypatch.setattr(ingestion, "QStashPublisher", _FakePublisher)


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


async def test_a_new_discovery_dispatches_both_its_jobs_to_qstash(db, qstash_configured) -> None:
    source = await _source(db)
    await import_feed_records(db, [_record(source.source_id, "https://example.test/a", "Award A")])

    kinds = sorted(call["body"]["kind"] for call in _FakePublisher.calls)
    assert kinds == ["link_canonical", "normalize_discovery"]
    for call in _FakePublisher.calls:
        assert call["destination"] == DESTINATION
        # QStash's own dedup, alongside enqueue_job's app-level dedup key check.
        assert call["deduplication_id"] == call["body"]["dedupe_key"]

    jobs = {job.dedupe_key: job for job in await db.scalars(select(ProcessingJob))}
    for call in _FakePublisher.calls:
        assert call["body"]["dedupe_key"] in jobs
        assert call["body"]["payload"] == jobs[call["body"]["dedupe_key"]].payload


async def test_a_repeated_row_dispatches_nothing_new(db, qstash_configured) -> None:
    source = await _source(db)
    record = _record(source.source_id, "https://example.test/a", "Award A")
    await import_feed_records(db, [record])
    _FakePublisher.calls.clear()

    await import_feed_records(db, [record])
    assert _FakePublisher.calls == []


async def test_qstash_being_unreachable_does_not_fail_the_import(db, qstash_configured) -> None:
    """A publish failure is best-effort: the import already committed, and the
    local ProcessingJob row still exists for run-due to pick up later."""
    _FakePublisher.fail_kinds = {"link_canonical"}
    source = await _source(db)
    outcome = await import_feed_records(
        db, [_record(source.source_id, "https://example.test/a", "Award A")]
    )
    assert outcome.imported == 1
    jobs = list(await db.scalars(select(ProcessingJob)))
    assert len(jobs) == 2, "both jobs are still durably persisted despite one publish failing"
    assert {job.state for job in jobs} == {"queued"}


async def test_nothing_is_dispatched_when_qstash_is_not_configured(db) -> None:
    """The default test/local state: no QSTASH_TOKEN set. Must not attempt a
    real network call, and must not fail the import either."""
    source = await _source(db)
    outcome = await import_feed_records(
        db, [_record(source.source_id, "https://example.test/a", "Award A")]
    )
    assert outcome.imported == 1
    assert _FakePublisher.calls == []
