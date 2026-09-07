"""Idempotently create the "Official Cycle Pages" Source that `reverify_due`
attaches every reverified cycle's SourcePage to.

`reverify_due` (app/infra/freshness.py) always passes its own
`approved_domains_override` per call - a reviewer-approved official_cycle_url
is authorized per-record at publish time, not pre-vetted per-domain the way
this row's own `approved_domains` would normally mean - so that field is
functionally unused here. SourceCreateRequest still requires at least one
entry (schema-level `min_length=1`), hence the clearly-labelled placeholder
below rather than an empty list.

Usage:
    uv run python scripts/create_official_cycle_source.py \\
        --base-url https://your-app.example.com --token $env:INTERNAL_SERVICE_TOKEN
"""

from __future__ import annotations

import argparse
import os
import sys

import httpx

OFFICIAL_SOURCE_NAME = "Official Cycle Pages"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--token", default=os.environ.get("INTERNAL_SERVICE_TOKEN"))
    args = parser.parse_args()
    if not args.token:
        print("FAIL: no --token given and INTERNAL_SERVICE_TOKEN is not set")
        return 1

    base = args.base_url.rstrip("/") + "/api/v1/internal/admin/sources"
    headers = {"X-Service-Token": args.token}
    with httpx.Client(headers=headers, timeout=30.0) as client:
        existing = client.get(base)
        existing.raise_for_status()
        for source in existing.json()["data"]:
            if source["name"] == OFFICIAL_SOURCE_NAME:
                print(f"OK: already exists (source_id={source['source_id']})")
                return 0

        response = client.post(
            base,
            json={
                "name": OFFICIAL_SOURCE_NAME,
                "source_type": "official_direct",
                "authority_grade": "A",
                # Never actually consulted - reverify_due always overrides
                # the allowlist per call. See module docstring.
                "approved_domains": ["unused.invalid"],
                "active": True,
            },
        )
    print(response.status_code, response.text)
    return 0 if response.status_code < 300 else 1


if __name__ == "__main__":
    sys.exit(main())
