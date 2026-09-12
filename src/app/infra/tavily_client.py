"""HTTP adapter for Tavily's Search API (https://api.tavily.com/search).

A Tier-C discovery source, the same evidentiary bucket as Parse.bot and
ScholarshipRegion (see docs/candidate-verification-standard.md): useful for
surfacing candidate URLs across whatever domain each result actually lands
on, never evidence on its own. Plain httpx, no vendor SDK - matching how
this codebase already calls the AI Router/Core/QStash directly.
"""

from __future__ import annotations

import httpx

SEARCH_URL = "https://api.tavily.com/search"

#: Deliberately conservative per call - enough for a representative sample
#: without spending the monthly credit budget on exhaustive pagination.
#: Mirrors RESULTS_PER_CALL's role in parsebot_client.py.
RESULTS_PER_CALL = 5


async def search_tavily(
    query: str,
    api_key: str,
    *,
    max_results: int = RESULTS_PER_CALL,
    timeout_seconds: float = 30.0,
) -> list[dict]:
    """One query's worth of results, as plain dicts (title/url/content/score).

    Raises httpx.HTTPError on any transport/HTTP failure - callers decide
    whether that means "skip this query" or should propagate, same as any
    other best-effort external call in this codebase.
    """
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            SEARCH_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"query": query, "max_results": max_results, "search_depth": "basic"},
        )
        response.raise_for_status()
        data = response.json()
    results = data.get("results")
    return results if isinstance(results, list) else []
