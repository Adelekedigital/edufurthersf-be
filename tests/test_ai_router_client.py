import httpx
import pytest

from app.domain.ai_router import AIRouterOutcome, AIRouterRequest, AITask
from app.infra.ai_router_client import AIRouterClient


def _request(**overrides: object) -> AIRouterRequest:
    defaults: dict[str, object] = dict(
        task=AITask.scholarship_extraction,
        task_version="v1",
        schema_version=1,
        product_id="scholarship_finder",
        feature_id="review_draft",
        correlation_id="corr-123",
        idempotency_key="idem-123456789",
        source_data={"raw_title": "Award A", "raw_excerpt": "An award."},
    )
    defaults.update(overrides)
    return AIRouterRequest(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_execute_sends_the_documented_contract_shape() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers["authorization"]
        seen["idempotency_header"] = request.headers["idempotency-key"]
        seen["url"] = str(request.url)
        seen["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "request_id": "req-1",
                "status": "completed",
                "output": {"funding_amount": "£10,000"},
                "model_policy_version": "policy-v1",
                "trace_reference": "trace-1",
            },
        )

    original = httpx.AsyncClient

    class TestClient(httpx.AsyncClient):
        def __init__(self, *args: object, **kwargs: object) -> None:
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    httpx.AsyncClient = TestClient  # type: ignore[assignment]
    try:
        result = await AIRouterClient("https://ai-router.test", "router-secret").execute(
            _request()
        )
    finally:
        httpx.AsyncClient = original  # type: ignore[assignment]

    assert seen["url"] == "https://ai-router.test/api/v1/internal/ai/execute"
    assert seen["authorization"] == "Bearer router-secret"
    assert seen["idempotency_header"] == "idem-123456789"
    assert "Award A" in str(seen["body"])
    assert result.request_id == "req-1"
    assert result.outcome == AIRouterOutcome.completed
    assert result.output == {"funding_amount": "£10,000"}
    assert result.trace_reference == "trace-1"


@pytest.mark.asyncio
async def test_execute_trims_a_trailing_slash_on_the_base_url() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(
            200,
            json={"request_id": "req-2", "status": "completed", "output": None,
                  "model_policy_version": None, "trace_reference": None},
        )

    original = httpx.AsyncClient

    class TestClient(httpx.AsyncClient):
        def __init__(self, *args: object, **kwargs: object) -> None:
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    httpx.AsyncClient = TestClient  # type: ignore[assignment]
    try:
        await AIRouterClient("https://ai-router.test/", "router-secret").execute(_request())
    finally:
        httpx.AsyncClient = original  # type: ignore[assignment]

    assert seen["url"] == "https://ai-router.test/api/v1/internal/ai/execute"


@pytest.mark.asyncio
async def test_execute_rejects_a_non_object_response() -> None:
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
            await AIRouterClient("https://ai-router.test", "router-secret").execute(_request())
    finally:
        httpx.AsyncClient = original  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_execute_raises_on_an_http_error_status() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "router unavailable"})

    original = httpx.AsyncClient

    class TestClient(httpx.AsyncClient):
        def __init__(self, *args: object, **kwargs: object) -> None:
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    httpx.AsyncClient = TestClient  # type: ignore[assignment]
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await AIRouterClient("https://ai-router.test", "router-secret").execute(_request())
    finally:
        httpx.AsyncClient = original  # type: ignore[assignment]
