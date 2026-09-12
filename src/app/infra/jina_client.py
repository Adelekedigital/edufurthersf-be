"""HTTP adapter for Jina.ai's Reader API (https://r.jina.ai).

A fetch fallback for pages the direct fetcher (source_fetch.py) can't
retrieve cleanly - transport failures, or a page that actively blocks the
direct request. Jina renders the target server-side and returns clean
markdown, so the result still satisfies the candidate-verification
standard's evidence bar ("a real page, actually fetched") - it changes how
the bytes get here, never what counts as evidence.
"""

from __future__ import annotations

import httpx

READER_BASE_URL = "https://r.jina.ai"


async def fetch_via_jina(url: str, api_key: str, *, timeout_seconds: float = 30.0) -> str:
    """Fetch `url` through Jina's Reader and return its markdown content.

    Raises httpx.HTTPError on any transport/HTTP failure - callers decide
    whether that means "no fallback available this time" or should
    propagate, same as any other best-effort external call in this codebase
    (see `_try_ai_extraction` in infra/worker.py).
    """
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.get(
            f"{READER_BASE_URL}/{url}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        response.raise_for_status()
        return response.text
