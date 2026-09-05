"""A 429 must carry both a specific RFC7807 code and a Retry-After header -
neither existed before this pass, leaving a caller with no signal for how
long to actually wait, and no way to distinguish a rate limit from any other
4xx by machine-readable code alone."""

from __future__ import annotations

import pytest

from app.api.routes import join_limiter, search_limiter
from app.core.config import get_settings
from tests.conftest import requires_db

pytestmark = requires_db

SEARCH = {
    "origin_country": "NG",
    "program_level": "masters",
    "field": "health_and_welfare",
    "target_countries": ["CA"],
}


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """Both limiters are module-level singletons shared across the whole test
    session, keyed by client host - exhausting one here must not bleed into
    any other test that happens to run afterward."""
    search_limiter._requests.clear()
    join_limiter._requests.clear()
    yield
    search_limiter._requests.clear()
    join_limiter._requests.clear()


@pytest.mark.anyio
async def test_search_rate_limit_returns_a_specific_code_and_retry_after(db, client) -> None:
    limit = get_settings().api_rate_limit_per_minute
    for _ in range(limit):
        response = await client.post("/api/v1/search", json=SEARCH)
        assert response.status_code == 200, response.text
    response = await client.post("/api/v1/search", json=SEARCH)
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
    body = response.json()
    assert body["code"] == "RATE_LIMIT_EXCEEDED"
    assert response.headers["content-type"].startswith("application/problem+json")
