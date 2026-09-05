"""Map raw Parse.bot marketplace API results into feed-import fields.

Pure functions only - no network I/O, no SDK types. `infra/parsebot_client.py`
is the only place that talks to Parse.bot; it hands this module plain dicts
already pulled off the SDK's typed objects, so this stays unit-testable with
fixtures and never imports `parse_apis`.

Never carries a deadline into `source_posted_at`/`feed_created_at`: those are
discovery/publication signals only, exactly the same rule the CSV feed import
already enforces (README's "Feed import" section) - an application deadline
is a fact only a human reviewer asserts, at publish time, from the real page.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

#: Fixed Source names this job looks up by - registered once via
#: scripts/manage_parsebot_sources.py, deactivating either one (the existing
#: POST /internal/admin/sources/{id}/deactivate) stops that API's harvest
#: without redeploying anything.
SCHOLARSHIPPORTAL_SOURCE_NAME = "ScholarshipPortal (via Parse.bot)"
PHDSCANNER_SOURCE_NAME = "PhDScanner (via Parse.bot)"


@dataclass(frozen=True)
class HarvestedRecord:
    title: str
    url: str
    excerpt: str | None
    feed_created_at: datetime | None


def scholarship_to_record(raw: dict, *, harvested_at: datetime) -> HarvestedRecord | None:
    """Map one ScholarshipPortal `Scholarship` (as a plain dict) to a record.

    `raw` carries whatever fields the SDK's `Scholarship` resource exposes:
    title, url, benefits, deadline, provider. ScholarshipPortal has no
    per-item discovery timestamp, so `feed_created_at` is this harvest run's
    own time - an honest "we found this then" signal, not a fabricated one.
    """
    title = (raw.get("title") or "").strip()
    url = (raw.get("url") or "").strip()
    if not title or not url:
        return None
    provider = (
        (raw.get("provider") or {}).get("name") if isinstance(raw.get("provider"), dict) else None
    )
    parts = [part for part in (provider, raw.get("benefits"), raw.get("deadline")) if part]
    excerpt = " | ".join(str(part) for part in parts) or None
    return HarvestedRecord(title=title, url=url, excerpt=excerpt, feed_created_at=harvested_at)


def opportunity_to_record(raw: dict, *, harvested_at: datetime) -> HarvestedRecord | None:
    """Map one PhDScanner `Opportunity` (as a plain dict) to a record.

    `created_at` is PhDScanner's own discovery timestamp (a Unix epoch
    seconds int) - a genuine third-party freshness signal, used as
    `feed_created_at` in preference to this harvest run's own time.
    `closing_date` is deliberately never read here: it is an application
    deadline, not a discovery signal.
    """
    title = (raw.get("title") or "").strip()
    url = (raw.get("opportunity_url") or "").strip()
    if not title or not url:
        return None
    parts = [
        part for part in (raw.get("university"), raw.get("department"), raw.get("category")) if part
    ]
    excerpt = " | ".join(str(part) for part in parts) or None
    created_at = raw.get("created_at")
    feed_created_at = (
        datetime.fromtimestamp(created_at, tz=UTC)
        if isinstance(created_at, (int, float))
        else harvested_at
    )
    return HarvestedRecord(title=title, url=url, excerpt=excerpt, feed_created_at=feed_created_at)
