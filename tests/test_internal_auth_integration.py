"""Authentication on the internal service and QStash job boundaries."""

from __future__ import annotations

import base64
import hashlib
import time

import jwt
import pytest

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
    body = b'{"kind":"normalize_discovery","dedupe_key":"job-1","payload":{}}'
    headers = {"Upstash-Signature": _sign(body), "Content-Type": "application/json"}
    first = await client.post("/api/v1/internal/jobs", content=body, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["created"] is True

    second = await client.post("/api/v1/internal/jobs", content=body, headers=headers)
    assert second.status_code == 200
    assert second.json()["created"] is False, "a replayed delivery must not create a second job"
    assert second.json()["job_id"] == first.json()["job_id"]


async def test_job_signed_with_the_next_key_is_accepted(client) -> None:
    body = b'{"kind":"normalize_discovery","dedupe_key":"job-rotate","payload":{}}'
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
