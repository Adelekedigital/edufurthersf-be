"""Authentication on the internal service and QStash job boundaries."""

from __future__ import annotations

import base64
import hashlib
import time

import jwt
import pytest
from sqlalchemy import select

from app.api.ingestion_schemas import FeedRecord
from app.domain.models import Discovery, ReviewTask, Source
from app.infra.ingestion import import_feed_records
from tests.conftest import requires_db

pytestmark = requires_db

DESTINATION = "https://finder.test/api/v1/internal/jobs"
CURRENT_KEY = "integration-current-signing-key-0123456789"
NEXT_KEY = "integration-next-signing-key-0123456789"


@pytest.fixture(autouse=True)
def _qstash_settings(monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "qstash_current_signing_key", CURRENT_KEY, raising=False)
    monkeypatch.setattr(settings, "qstash_next_signing_key", NEXT_KEY, raising=False)
    monkeypatch.setattr(settings, "qstash_expected_destination", DESTINATION, raising=False)


def _sign(body: bytes, *, key: str = CURRENT_KEY, sub: str = DESTINATION) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": "Upstash",
            "sub": sub,
            "exp": now + 300,
            "nbf": now - 10,
            "iat": now,
            # Padded, exactly as QStash sends it.
            "body": base64.urlsafe_b64encode(hashlib.sha256(body).digest()).decode(),
        },
        key,
        algorithm="HS256",
    )


async def test_signed_job_is_accepted_and_replay_is_deduplicated(client) -> None:
    # dispatch_outbox needs no payload and always succeeds, since this test is
    # about signature/dedup mechanics, not about one job kind's own business
    # logic - execute_job now runs inline, so the job must actually complete.
    body = b'{"kind":"dispatch_outbox","dedupe_key":"job-1","payload":{}}'
    headers = {"Upstash-Signature": _sign(body), "Content-Type": "application/json"}
    first = await client.post("/api/v1/internal/jobs", content=body, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["created"] is True
    assert first.json()["state"] == "completed"

    second = await client.post("/api/v1/internal/jobs", content=body, headers=headers)
    assert second.status_code == 200
    assert second.json()["created"] is False, "a replayed delivery must not create a second job"
    assert second.json()["job_id"] == first.json()["job_id"]
    assert second.json()["state"] == "completed", "a replay must not re-run a completed job"


async def test_job_signed_with_the_next_key_is_accepted(client) -> None:
    body = b'{"kind":"dispatch_outbox","dedupe_key":"job-rotate","payload":{}}'
    headers = {"Upstash-Signature": _sign(body, key=NEXT_KEY)}
    assert (
        await client.post("/api/v1/internal/jobs", content=body, headers=headers)
    ).status_code == 200


async def test_unsigned_job_is_rejected(client) -> None:
    body = b'{"kind":"normalize_discovery","dedupe_key":"job-2","payload":{}}'
    assert (await client.post("/api/v1/internal/jobs", content=body)).status_code == 401


async def test_signature_for_another_destination_is_rejected(client) -> None:
    body = b'{"kind":"normalize_discovery","dedupe_key":"job-3","payload":{}}'
    signature = _sign(body, sub="https://other.test/api/v1/internal/jobs")
    response = await client.post(
        "/api/v1/internal/jobs", content=body, headers={"Upstash-Signature": signature}
    )
    assert response.status_code == 401


async def test_tampered_body_is_rejected(client) -> None:
    body = b'{"kind":"normalize_discovery","dedupe_key":"job-4","payload":{}}'
    signature = _sign(body)
    tampered = b'{"kind":"normalize_discovery","dedupe_key":"job-5","payload":{}}'
    response = await client.post(
        "/api/v1/internal/jobs", content=tampered, headers={"Upstash-Signature": signature}
    )
    assert response.status_code == 401


async def test_job_kinds_are_not_disclosed_before_authentication(client) -> None:
    body = b'{"kind":"arbitrary_code","dedupe_key":"job-6","payload":{}}'
    response = await client.post("/api/v1/internal/jobs", content=body)
    assert response.status_code == 401, "an unauthenticated caller must not learn which kinds exist"


async def test_internal_endpoint_requires_the_service_token(client) -> None:
    payload = {"records": []}
    assert (await client.post("/api/v1/internal/import/feed", json=payload)).status_code == 401
    wrong = {"X-Service-Token": "not-the-token"}
    assert (
        await client.post("/api/v1/internal/import/feed", json=payload, headers=wrong)
    ).status_code == 401
    # With the correct token the request reaches validation instead of being
    # refused, which is what distinguishes an auth failure from a bad payload.
    right = {"X-Service-Token": "internal-service-token"}
    accepted = await client.post("/api/v1/internal/import/feed", json=payload, headers=right)
    assert accepted.status_code == 422, accepted.text


async def test_a_real_qstash_delivery_actually_runs_the_job(db, client) -> None:
    """A signed link_canonical delivery for a real discovery must reach the
    review queue through the exact HTTP path QStash uses - not just through
    calling execute_job directly, the way other tests deliberately do."""
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
        db,
        [
            FeedRecord(
                source_id=source.source_id,
                url="https://example.test/award",
                title="Award A",
                excerpt="An award",
            )
        ],
    )
    discovery = await db.scalar(select(Discovery))
    assert discovery.processing_state == "normalized"

    body = (
        '{"kind":"link_canonical","dedupe_key":"link-e2e-1",'
        f'"payload":{{"discovery_id":"{discovery.discovery_id}"}}}}'
    ).encode()
    headers = {"Upstash-Signature": _sign(body)}
    response = await client.post("/api/v1/internal/jobs", content=body, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "completed"

    task = await db.scalar(
        select(ReviewTask).where(ReviewTask.discovery_id == discovery.discovery_id)
    )
    assert task is not None, "the QStash delivery must have actually run link_discovery"
