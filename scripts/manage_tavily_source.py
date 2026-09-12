"""Register or deactivate the Tavily-backed Source the weekly harvest job
(`harvest_tavily`) looks up by name.

Deactivating it is the app-level kill switch: `harvest_tavily` skips the
network calls entirely on its next run, no redeploy needed, using the
existing admin endpoints (`POST /internal/admin/sources`,
`POST /internal/admin/sources/{id}/deactivate`). For a hard stop on the
QStash schedule itself, see scripts/manage_tavily_schedule.py pause.

Note on `approved_domains`: Tavily's discovered URLs land on whatever real
domain each search result happens to be on (a government portal, a
university site, ...), not one fixed domain the way Parse.bot's marketplace
APIs are. The value below is this Source's own identity, not a claim about
where its discoveries live - nothing in the automated pipeline re-fetches a
Tavily-discovered page directly; a reviewer doing that by hand would use
`fetch_and_persist_page`'s `approved_domains_override` for that one page.

Usage (uv run python scripts/manage_tavily_source.py <command> ...,
each needs --base-url https://your-app.example.com --token $env:INTERNAL_SERVICE_TOKEN):
    create
    deactivate
"""

from __future__ import annotations

import argparse
import os

import httpx

from app.domain.tavily_harvest import TAVILY_SOURCE_NAME

SOURCE_PAYLOAD = {
    "name": TAVILY_SOURCE_NAME,
    "source_type": "web_search",
    "authority_grade": "C",
    "approved_domains": ["tavily.com"],
    "active": True,
}


def create(args: argparse.Namespace) -> int:
    with httpx.Client(
        base_url=args.base_url, headers={"X-Service-Token": args.token}, timeout=30.0
    ) as client:
        response = client.post("/api/v1/internal/admin/sources", json=SOURCE_PAYLOAD)
    print(response.status_code, response.text)
    return 0 if response.status_code < 300 else 1


def deactivate(args: argparse.Namespace) -> int:
    with httpx.Client(
        base_url=args.base_url, headers={"X-Service-Token": args.token}, timeout=30.0
    ) as client:
        listing = client.get("/api/v1/internal/admin/sources").json()["data"]
        by_name = {row["name"]: row["source_id"] for row in listing}
        source_id = by_name.get(TAVILY_SOURCE_NAME)
        if source_id is None:
            print("SKIP: not registered yet - run `create` first")
            return 0
        response = client.post(f"/api/v1/internal/admin/sources/{source_id}/deactivate")
    print(response.status_code, response.text)
    return 0 if response.status_code < 300 else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--token", default=os.environ.get("INTERNAL_SERVICE_TOKEN"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("create").set_defaults(func=create)
    sub.add_parser("deactivate").set_defaults(func=deactivate)

    args = parser.parse_args()
    if not args.token:
        print("FAIL: no --token given and INTERNAL_SERVICE_TOKEN is not set")
        return 1
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
