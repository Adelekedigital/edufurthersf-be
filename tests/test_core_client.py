import httpx
import pytest

from app.infra.core_client import CoreJoinClient


@pytest.mark.asyncio
async def test_core_join_client_sends_service_auth_and_idempotency() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers["authorization"]
        seen["idempotency"] = request.headers["idempotency-key"]
        seen["payload"] = request.read().decode()
        return httpx.Response(200, json={"id": "core-123", "status": "created"})

    original = httpx.AsyncClient

    class TestClient(httpx.AsyncClient):
        def __init__(self, *args: object, **kwargs: object) -> None:
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    httpx.AsyncClient = TestClient  # type: ignore[assignment]
    try:
        result = await CoreJoinClient("https://core.test/join", "secret").create_join_intent(
            {"source_product": "scholarship_finder"}, "request-123456789"
        )
    finally:
        httpx.AsyncClient = original  # type: ignore[assignment]

    assert result == {"id": "core-123", "status": "created"}
    assert seen["authorization"] == "Bearer secret"
    assert seen["idempotency"] == "request-123456789"


@pytest.mark.asyncio
async def test_core_join_client_rejects_non_object_response() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["unexpected"])

    original = httpx.AsyncClient

    class TestClient(httpx.AsyncClient):
        def __init__(self, *args: object, **kwargs: object) -> None:
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    httpx.AsyncClient = TestClient  # type: ignore[assignment]
    try:
        with pytest.raises(ValueError, match="must be an object"):
            await CoreJoinClient("https://core.test/join", "secret").create_join_intent(
                {}, "request-123456789"
            )
    finally:
        httpx.AsyncClient = original  # type: ignore[assignment]
