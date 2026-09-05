"""Register, activate, or deactivate the two Parse.bot-backed Sources the
weekly harvest job (`harvest_parsebot`) looks up by name.

Deactivating either one is the app-level kill switch: `harvest_parsebot`
skips that API's network calls entirely on its next run, no redeploy needed,
using the existing admin endpoints (`POST /internal/admin/sources`,
`POST /internal/admin/sources/{id}/deactivate`). For a hard stop on the
QStash schedule itself, see scripts/manage_parsebot_schedule.py pause.

Usage (uv run python scripts/manage_parsebot_sources.py <command> ...,
each needs --base-url https://your-app.example.com --token $env:INTERNAL_SERVICE_TOKEN):
    create
    deactivate --which scholarshipportal
    deactivate --which phdscanner
    deactivate --which both
"""

from __future__ import annotations

import argparse
import os

import httpx

from app.domain.parsebot_harvest import PHDSCANNER_SOURCE_NAME, SCHOLARSHIPPORTAL_SOURCE_NAME

SOURCES = {
    "scholarshipportal": {
        "name": SCHOLARSHIPPORTAL_SOURCE_NAME,
        "source_type": "parsebot_api",
        "authority_grade": "C",
        "approved_domains": ["scholarshipportal.com"],
        "active": True,
    },
    "phdscanner": {
        "name": PHDSCANNER_SOURCE_NAME,
        "source_type": "parsebot_api",
        "authority_grade": "C",
        "approved_domains": ["phdscanner.com"],
        "active": True,
    },
}


def create(args: argparse.Namespace) -> int:
    with httpx.Client(
        base_url=args.base_url, headers={"X-Service-Token": args.token}, timeout=30.0
    ) as client:
        for key, payload in SOURCES.items():
            response = client.post("/api/v1/internal/admin/sources", json=payload)
            print(key, response.status_code, response.text)
    return 0


def _which(args: argparse.Namespace) -> list[str]:
    return list(SOURCES) if args.which == "both" else [args.which]


def deactivate(args: argparse.Namespace) -> int:
    with httpx.Client(
        base_url=args.base_url, headers={"X-Service-Token": args.token}, timeout=30.0
    ) as client:
        listing = client.get("/api/v1/internal/admin/sources").json()["data"]
        by_name = {row["name"]: row["source_id"] for row in listing}
        for key in _which(args):
            name = SOURCES[key]["name"]
            source_id = by_name.get(name)
            if source_id is None:
                print(key, "SKIP: not registered yet - run `create` first")
                continue
            response = client.post(f"/api/v1/internal/admin/sources/{source_id}/deactivate")
            print(key, response.status_code, response.text)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--token", default=os.environ.get("INTERNAL_SERVICE_TOKEN"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("create").set_defaults(func=create)
    p_deactivate = sub.add_parser("deactivate")
    p_deactivate.add_argument(
        "--which", choices=["scholarshipportal", "phdscanner", "both"], default="both"
    )
    p_deactivate.set_defaults(func=deactivate)

    args = parser.parse_args()
    if not args.token:
        print("FAIL: no --token given and INTERNAL_SERVICE_TOKEN is not set")
        return 1
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
