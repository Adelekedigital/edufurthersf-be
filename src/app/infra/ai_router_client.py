"""HTTP adapter for the shared Edufurther AI Router.

Not a live integration yet: no adapter is wired into any job, because no
router deployment exists to point it at. Building this now against the
documented contract (Analytics & Metrics Standard §5,
`POST /api/v1/internal/ai/execute`) means the day the router is provisioned
as its own service, wiring it in is a config value and a call site, not a
new integration to design.
"""

from dataclasses import dataclass
from typing import Any

import httpx

from app.domain.ai_router import (
    DEFAULT_TIMEOUT_SECONDS,
    AIRouterOutcome,
    AIRouterRequest,
    AIRouterResponse,
)


@dataclass(frozen=True)
class AIRouterClient:
    base_url: str
    service_token: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    async def execute(self, request: AIRouterRequest) -> AIRouterResponse:
        payload: dict[str, Any] = {
            "product_id": request.product_id,
            "feature_id": request.feature_id,
            "task": request.task.value,
            "task_version": request.task_version,
            "schema_version": request.schema_version,
            "correlation_id": request.correlation_id,
            "idempotency_key": request.idempotency_key,
            "source_data": request.source_data,
            "journey_id": request.journey_id,
            "session_id": request.session_id,
            "handoff_id": request.handoff_id,
        }
        headers = {
            "Authorization": f"Bearer {self.service_token}",
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
