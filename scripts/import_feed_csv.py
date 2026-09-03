"""Bulk-import a CSV export of the Sheet (or the curated bucket list) through
POST /internal/import/feed.

Every row is validated locally against the exact contract the API enforces
before anything is sent. This matters because the import endpoint accepts up
to 500 records in one call, validated as a single Pydantic model: one row with
a blank Link or an unparsable URL would reject the *entire* batch, not just
that row. Rows that fail validation are reported and skipped; only the
survivors are sent, in batches under the API's own cap.

Server-side outcomes (imported / repeated / changed / rejected) are a separate
concern this script does not second-guess: an unknown source id or a URL that
fails canonicalisation still lands in DiscoveryQuarantine, exactly as importing
through the API directly would.

Usage:
    uv run python scripts/import_feed_csv.py export.csv --source-id <uuid> \
        --base-url https://finder.example.com --token $INTERNAL_SERVICE_TOKEN

    # Validate the file without sending anything:
    uv run python scripts/import_feed_csv.py export.csv --source-id <uuid> --dry-run

Expects the Sheet's five known columns, matched case-insensitively by a small
set of aliases: Title, Description (or Excerpt), Link (or URL), Source Posted
Date, Created Date. The two dates are optional and, when present in the feed,
are discovery/publication signals only - never application deadlines - passed
through unchanged.
"""

from __future__ import annotations

import argparse
import csv
import os
import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import httpx
from pydantic import ValidationError

from app.api.ingestion_schemas import FeedRecord

#: The API's own per-request cap (FeedImportRequest.records max_length).
API_BATCH_CAP = 500

_HEADER_ALIASES: dict[str, set[str]] = {
    "title": {"title"},
    "excerpt": {"description", "excerpt"},
    "url": {"link", "url"},
    "source_posted_at": {"source posted date", "source_posted_at", "posted date"},
    "feed_created_at": {"created date", "feed_created_at", "created_at"},
}

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y %H:%M:%S")


def _normalize_header(name: str) -> str:
    return name.strip().lower()


def _resolve_columns(fieldnames: list[str]) -> dict[str, str]:
    """Map this CSV's actual header names onto the fields FeedRecord expects."""
    normalized = {_normalize_header(name): name for name in fieldnames}
    resolved: dict[str, str] = {}
    for field, aliases in _HEADER_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                resolved[field] = normalized[alias]
                break
    missing = {"title", "url"} - resolved.keys()
    if missing:
        raise SystemExit(
            f"CSV is missing required column(s) matching: {sorted(missing)}. "
            f"Headers found: {fieldnames}"
        )
    return resolved


def _parse_date(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _read_rows(path: str, source_id: uuid.UUID) -> Iterator[tuple[int, FeedRecord | str]]:
    """Yield (row_number, FeedRecord) for a valid row, or (row_number, error) for
    one that fails local validation."""
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise SystemExit("CSV has no header row")
        columns = _resolve_columns(list(reader.fieldnames))
        for row_number, row in enumerate(reader, start=2):  # header is row 1
            title = (row.get(columns["title"]) or "").strip()
            url = (row.get(columns["url"]) or "").strip()
            excerpt = (row.get(columns.get("excerpt", ""), "") or "").strip() or None
            if not title and not url:
                continue  # a blank trailing line, not a real row
            posted_raw = row.get(columns.get("source_posted_at", ""), "") or ""
            created_raw = row.get(columns.get("feed_created_at", ""), "") or ""
            try:
                record = FeedRecord(
                    source_id=source_id,
                    url=url,
                    title=title,
                    excerpt=excerpt,
                    source_posted_at=_parse_date(posted_raw),
                    feed_created_at=_parse_date(created_raw),
                )
            except ValidationError as exc:
                yield (
                    row_number,
                    "; ".join(
                        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                        for error in exc.errors()
                    ),
                )
                continue
            yield row_number, record


def _batches(records: list[FeedRecord], size: int) -> Iterator[list[FeedRecord]]:
    for start in range(0, len(records), size):
        yield records[start : start + size]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("csv_path", help="Path to the CSV export")
    parser.add_argument(
        "--source-id", required=True, type=uuid.UUID, help="Existing Source's source_id"
    )
    parser.add_argument(
        "--base-url", default=os.environ.get("FINDER_BASE_URL", "http://127.0.0.1:8000")
    )
    parser.add_argument("--token", default=os.environ.get("INTERNAL_SERVICE_TOKEN"))
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help=f"Rows per API call, up to the server's cap of {API_BATCH_CAP}",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate the file only; send nothing"
    )
    args = parser.parse_args()

    batch_size = min(args.batch_size, API_BATCH_CAP)
    records: list[FeedRecord] = []
    problems: list[tuple[int, str]] = []
    for row_number, result in _read_rows(args.csv_path, args.source_id):
        if isinstance(result, str):
            problems.append((row_number, result))
        else:
            records.append(result)

    total_rows = len(records) + len(problems)
    print(f"Parsed {total_rows} rows: {len(records)} valid, {len(problems)} rejected locally")
    for row_number, reason in problems[:20]:
        print(f"  row {row_number}: {reason}")
    if len(problems) > 20:
        print(f"  ... and {len(problems) - 20} more")

    if not records:
        print("Nothing to import.")
        return 1 if problems else 0

    if args.dry_run:
        batch_count = -(-len(records) // batch_size)
        print(f"Dry run: would send {len(records)} rows in {batch_count} batch(es).")
        return 0

    if not args.token:
        print("FAIL: no --token given and INTERNAL_SERVICE_TOKEN is not set")
        return 1

    totals = {"imported": 0, "repeated": 0, "changed": 0, "rejected": 0}
    url = args.base_url.rstrip("/") + "/api/v1/internal/import/feed"
    with httpx.Client(timeout=60.0) as client:
        for index, batch in enumerate(_batches(records, batch_size), start=1):
            payload: dict[str, Any] = {
                "records": [record.model_dump(mode="json") for record in batch]
            }
            response = client.post(url, json=payload, headers={"X-Service-Token": args.token})
            if response.status_code != 200:
                print(
                    f"FAIL batch {index} ({len(batch)} rows): "
                    f"HTTP {response.status_code} {response.text[:500]}"
                )
                return 1
            body = response.json()
            for key in totals:
                totals[key] += body[key]
            print(
                f"batch {index}: {len(batch)} rows -> imported={body['imported']} "
                f"repeated={body['repeated']} changed={body['changed']} "
                f"rejected={body['rejected']} crawl_run_id={body['crawl_run_id']}"
            )

    print(
        f"Done. Totals: imported={totals['imported']} repeated={totals['repeated']} "
        f"changed={totals['changed']} rejected={totals['rejected']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
