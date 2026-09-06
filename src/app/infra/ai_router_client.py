"""HTTP adapter for the shared Edufurther AI Router.

Authenticates the way the Router's own integration doc requires
(docs/integration-scholarship-finder.md on the router side): a short-lived
RS256 JWT signed in-process with Finder's own private key. The Router only
ever verifies a registered public key - it never issues, holds, or
transmits Finder's private key, so there is no bearer secret to leak here,
only a keypair Finder owns end to end.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt

from app.domain.ai_router import (
    DEFAULT_TIMEOUT_SECONDS,
    AIRouterOutcome,
    AIRouterRequest,
    AIRouterResponse,
)

#: Fixed identifiers coordinated with the Router admin's SERVICE_CALLERS
#: registration - never vary these per environment or per call; a change
#: here requires re-registering the public key under the new values.
SUBJECT = "scholarship-finder-worker"
ISSUER = "scholarship-finder"
AUDIENCE = "edufurther-ai-router"
SCOPE = "ai:execute"
#: The Router permanently rejects a reused `jti` and any token whose `exp`
#: is more than 300s past `iat` - keep well inside that bound.
TOKEN_LIFETIME_SECONDS = 120


@dataclass(frozen=True)
class AIRouterClient:
    base_url: str
    private_key_pem: str
    key_id: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    def _sign_jwt(self) -> str:
        now = datetime.now(UTC)
        claims = {
            "iss": ISSUER,
            "sub": SUBJECT,
            "aud": AUDIENCE,
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(seconds=TOKEN_LIFETIME_SECONDS),
            # Unique per call, not per logical unit of work - unlike
            # idempotency_key, a retried call must mint a fresh jti.
            "jti": str(uuid.uuid4()),
            "scope": SCOPE,
        }
        return jwt.encode(
            claims, self.private_key_pem, algorithm="RS256", headers={"kid": self.key_id}
        )

    async def execute(self, request: AIRouterRequest) -> AIRouterResponse:
        # Only what the Router's ExecuteRequest schema actually accepts
        # (extra="forbid" on its side) - task_version/schema_version are
        # Finder-internal bookkeeping on AIRouterRequest, never sent over
        # the wire.
        payload: dict[str, Any] = {
            "product_id": request.product_id,
            "feature_id": request.feature_id,
            "task": request.task.value,
            "correlation_id": request.correlation_id,
            "idempotency_key": request.idempotency_key,
            "source_data": request.source_data,
            "journey_id": request.journey_id,
            "session_id": request.session_id,
            "handoff_id": request.handoff_id,
        }
        headers = {
            "Authorization": f"Bearer {self._sign_jwt()}",
            "Idempotency-Key": request.idempotency_key,
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url.rstrip('/')}/api/v1/internal/ai/execute",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            body = response.json()
        if not isinstance(body, dict):
            raise ValueError("AI Router response must be an object")
        return AIRouterResponse(
            request_id=body["request_id"],
            outcome=AIRouterOutcome(body["status"]),
            output=body.get("output"),
            model_policy_version=body.get("model_policy_version"),
            trace_reference=body.get("trace_reference"),
        )
