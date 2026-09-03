from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class CoreJoinClient:
    endpoint: str
    service_token: str

    async def create_join_intent(
        self, payload: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.service_token}",
            "Idempotency-Key": idempotency_key,
        }
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(self.endpoint, json=payload, headers=headers)
            response.raise_for_status()
            body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Core join-intent response must be an object")
        return body
