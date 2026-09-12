"""Map raw Tavily search results into feed-import fields.

Pure functions only - no network I/O. `infra/tavily_client.py` is the only
place that talks to Tavily; it hands this module plain dicts already
parsed from the JSON response, so this stays unit-testable with fixtures
and never imports `httpx`.

Tier C, the same evidentiary bucket as Parse.bot/ScholarshipRegion (see
docs/candidate-verification-standard.md): a search result is a candidate
URL to review, never evidence on its own. Nothing here ever asserts a
funding amount or deadline - `excerpt` is only the raw search snippet, read
by a human reviewer against the real page before anything is published.
"""

from __future__ import annotations

from datetime import datetime

from app.domain.parsebot_harvest import HarvestedRecord

#: Registered once via scripts/manage_tavily_source.py - deactivating it
#: (the existing POST /internal/admin/sources/{id}/deactivate) stops
#: harvest_tavily's network calls without redeploying anything.
TAVILY_SOURCE_NAME = "Tavily Web Search"


def tavily_result_to_record(raw: dict, *, harvested_at: datetime) -> HarvestedRecord | None:
    """Map one Tavily search result (title/url/content/score) to a record.

    Tavily has no per-item discovery timestamp, so `feed_created_at` is this
    harvest run's own time - an honest "we found this then" signal, the
    same fallback ScholarshipPortal's mapping uses.
    """
    title = (raw.get("title") or "").strip()
    url = (raw.get("url") or "").strip()
    if not title or not url:
        return None
    excerpt = (raw.get("content") or "").strip() or None
    return HarvestedRecord(title=title, url=url, excerpt=excerpt, feed_created_at=harvested_at)
