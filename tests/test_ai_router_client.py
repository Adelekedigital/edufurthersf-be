"""The AI Router HTTP adapter: RS256 JWT signing and the wire payload shape.

Both matter for reasons a type checker can't catch - a wrong claim breaks
authentication (docs/integration-scholarship-finder.md,
docs/authentication.md on the router side), and an extra payload field
breaks the request outright since the router's schema has extra="forbid"."""

from __future__ import annotations

import json

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.domain.ai_router import AIRouterRequest, AITask
from app.infra.ai_router_client import (
    AUDIENCE,
    ISSUER,
    SCOPE,
    SUBJECT,
    TOKEN_LIFETIME_SECONDS,
    AIRouterClient,
)


def _client(private_pem: str) -> AIRouterClient:
    return AIRouterClient(
        base_url="https://router.test", private_key_pem=private_pem, key_id="kid-1"
    )


@pytest.fixture
def keypair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


def test_signed_jwt_carries_exactly_the_standards_required_claims(keypair) -> None:
    private_pem, public_pem = keypair
    client = _client(private_pem)

    token = client._sign_jwt()
    header = jwt.get_unverified_header(token)
    assert header["alg"] == "RS256"
    assert header["kid"] == "kid-1"

    claims = jwt.decode(token, public_pem, algorithms=["RS256"], audience=AUDIENCE)
    assert claims["iss"] == ISSUER
    assert claims["sub"] == SUBJECT
    assert claims["aud"] == AUDIENCE
    assert claims["scope"] == SCOPE
    assert claims["exp"] - claims["iat"] <= 300
    assert claims["exp"] - claims["iat"] == TOKEN_LIFETIME_SECONDS


def test_two_tokens_never_reuse_a_jti(keypair) -> None:
    private_pem, public_pem = keypair
    client = _client(private_pem)
    first = jwt.decode(client._sign_jwt(), public_pem, algorithms=["RS256"], audience=AUDIENCE)
    second = jwt.decode(client._sign_jwt(), public_pem, algorithms=["RS256"], audience=AUDIENCE)
    assert first["jti"] != second["jti"]


async def test_execute_never_sends_task_version_or_schema_version(keypair, monkeypatch) -> None:
    """The router's ExecuteRequest has extra="forbid" - these two fields
    exist on AIRouterRequest for Finder's own bookkeeping only."""
    private_pem, _ = keypair
    captured: dict = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["headers"] = dict(request.headers)
        return httpx.Response(
            200,
            json={
                "request_id": "req-1",
                "status": "completed",
                "output": {"a": 1},
                "model_policy_version": "v1",
                "trace_reference": None,
            },
        )

    original_client_cls = httpx.AsyncClient

    def _patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(_handler)
        return original_client_cls(*args, **kwargs)

    import app.infra.ai_router_client as module

    monkeypatch.setattr(module.httpx, "AsyncClient", _patched)
    client = _client(private_pem)
    request = AIRouterRequest(
        task=AITask.scholarship_extraction,
        task_version="v1",
        schema_version=1,
        product_id="scholarship_finder",
        feature_id="extract_candidate",
        correlation_id="corr-1",
        idempotency_key="idem-1",
        source_data={"raw_title": "Award A"},
    )
    response = await client.execute(request)

    assert "task_version" not in captured["body"]
    assert "schema_version" not in captured["body"]
    assert captured["body"]["product_id"] == "scholarship_finder"
    assert captured["headers"]["idempotency-key"] == "idem-1"
    assert captured["headers"]["authorization"].startswith("Bearer ")
    assert response.output == {"a": 1}
