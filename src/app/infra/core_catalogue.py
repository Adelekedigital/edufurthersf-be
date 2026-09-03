"""Read Core's public reference catalogues.

Core publishes these unauthenticated, so no service token is sent. This client
is used by a scheduled sync, never from the search path: search must keep
answering while Core is unavailable, which a per-request call would prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

#: Core caps a catalogue page; paging continues while it returns a cursor.
MAX_PAGES = 20


@dataclass(frozen=True)
class CatalogueEntry:
    """One lookup row: a stable code, a display name, and Core's own row id."""

    code: str
    display_name: str
    core_id: str | None


@dataclass(frozen=True)
class CoreCatalogueClient:
    base_url: str
    timeout_seconds: float = 10.0

    async def list_catalogue(self, name: str) -> list[CatalogueEntry]:
        """Return every row of one catalogue, following Core's cursor."""
        url = f"{self.base_url.rstrip('/')}/api/v1/catalog/{name}"
        entries: list[CatalogueEntry] = []
        cursor: str | None = None
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            for _ in range(MAX_PAGES):
                params = {"cursor": cursor} if cursor else None
                response = await client.get(url, params=params)
                response.raise_for_status()
                body: Any = response.json()
                if not isinstance(body, dict) or not isinstance(body.get("data"), list):
                    raise ValueError(f"Core catalogue {name!r} returned an unexpected envelope")
                for row in body["data"]:
                    code = row.get("code")
                    display_name = row.get("display_name")
                    # A row without a stable code cannot be mirrored: there
                    # would be nothing to match it to on the next sync.
                    if not code or not display_name:
                        continue
                    entries.append(
                        CatalogueEntry(
                            code=str(code), display_name=str(display_name), core_id=row.get("id")
                        )
                    )
                cursor = body.get("next_cursor")
                if not cursor:
                    return entries
        raise ValueError(f"Core catalogue {name!r} did not finish paging within {MAX_PAGES} pages")
