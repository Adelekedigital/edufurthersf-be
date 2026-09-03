"""Build the stored record of what a search response contained.

This is a bounded historical copy of one response page, not a second scholarship
catalogue and not a cache to serve later searches from. It holds the values that
were returned, so a click or a ranking complaint stays explainable after the
underlying record changes.

Nothing private belongs here: no emails, no Core credentials, no handoff token,
no IP address, no reviewer notes or source text. The pagination cursor is
deliberately dropped too — it is a bearer token, and this is a public-data copy
rather than a byte-for-byte archive of the HTTP response.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

SNAPSHOT_SCHEMA_VERSION = "snapshot-v1"

#: Every key permitted in a stored result object. A field added to the public
#: response is absent from the snapshot until it is listed here on purpose,
#: which is the direction the mistake should fall.
ALLOWED_RESULT_KEYS = frozenset(
    {
        "scholarship_id",
        "cycle_id",
        "name",
        "provider",
        "status",
        "fit",
        "official_url",
        "last_verified_at",
        "caveats",
    }
)


def _plain(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    return value if isinstance(value, (str, int, float, bool, type(None))) else str(value)


def build_result_snapshot(
    results: list[dict[str, Any]],
    *,
    evaluated_at: datetime,
    match_policy_version: str,
    taxonomy_version: str,
    page_number: int,
    requested_limit: int,
    total_match_count: int,
    has_next_page: bool,
    warnings: list[str],
) -> dict[str, Any]:
    """Return the versioned snapshot for one evaluated response page."""
    data = [
        {key: _plain(value) for key, value in result.items() if key in ALLOWED_RESULT_KEYS}
        for result in results
    ]
    rejected = sorted({key for result in results for key in result} - ALLOWED_RESULT_KEYS)
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "data": data,
        "meta": {
            "evaluated_at": evaluated_at.isoformat(),
            "match_policy_version": match_policy_version,
            "taxonomy_version": taxonomy_version,
            # The complete matching set, distinct from what this page returned.
            "total_match_count": total_match_count,
            "returned_count": len(data),
            "warnings": list(warnings),
            # Named rather than silently dropped, so an unlisted field is
            # visible as a decision instead of looking like data loss.
            "excluded_fields": rejected,
        },
        "pagination": {
            "page_number": page_number,
            "requested_limit": requested_limit,
            "has_next_page": has_next_page,
        },
    }
