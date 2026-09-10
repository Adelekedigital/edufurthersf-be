"""Create, pause, resume, inspect, or delete the weekly sync_countries
schedule on QStash.

The schedule delivers a static body to the app's stable `/internal/jobs`
callback on a cron cadence; `sync_countries`'s dedupe_key is recomputed
server-side per ISO week (see `RECURRING_WEEKLY_KINDS` in `app/api/routes.py`)
so the same static body still produces a fresh, real run every week rather
than being deduped against the first-ever delivery forever.

Requires CORE_BASE_URL to be configured on the app itself - without it,
every scheduled run fails identically (sync_countries is not in
RETRYABLE_KINDS, so a missing config fails straight to failed_review with
no auto-retry until the next week's delivery).

Usage (uv run python scripts/manage_sync_countries_schedule.py <command> ...):
    create --base-url https://your-app.example.com --token $env:QSTASH_TOKEN \\
        --cron "0 5 * * 1"   # every Monday 05:00 UTC, an hour before harvest_parsebot
    status  --token $env:QSTASH_TOKEN
    pause   --schedule-id <id> --token $env:QSTASH_TOKEN
    resume  --schedule-id <id> --token $env:QSTASH_TOKEN
    delete  --schedule-id <id> --token $env:QSTASH_TOKEN
"""

from __future__ import annotations

import argparse
import json
import os

import httpx

DEFAULT_QSTASH_URL = "https://qstash.upstash.io"


def _client(token: str) -> httpx.Client:
    return httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=30.0)


def create(args: argparse.Namespace) -> int:
    destination = args.base_url.rstrip("/") + "/api/v1/internal/jobs"
    body = {"kind": "sync_countries", "dedupe_key": "sync_countries:scheduled", "payload": {}}
    with _client(args.token) as client:
        response = client.post(
            f"{args.qstash_url}/v2/schedules/{destination}",
            headers={"Upstash-Cron": args.cron, "Content-Type": "application/json"},
            content=json.dumps(body),
        )
    print(response.status_code, response.text)
    return 0 if response.status_code < 300 else 1


def status(args: argparse.Namespace) -> int:
    with _client(args.token) as client:
        response = client.get(f"{args.qstash_url}/v2/schedules")
    print(response.status_code, response.text)
    return 0 if response.status_code < 300 else 1


def pause(args: argparse.Namespace) -> int:
    with _client(args.token) as client:
        response = client.post(f"{args.qstash_url}/v2/schedules/{args.schedule_id}/pause")
    print(response.status_code, response.text or "paused")
    return 0 if response.status_code < 300 else 1


def resume(args: argparse.Namespace) -> int:
    with _client(args.token) as client:
        response = client.post(f"{args.qstash_url}/v2/schedules/{args.schedule_id}/resume")
    print(response.status_code, response.text or "resumed")
    return 0 if response.status_code < 300 else 1


def delete(args: argparse.Namespace) -> int:
    with _client(args.token) as client:
        response = client.delete(f"{args.qstash_url}/v2/schedules/{args.schedule_id}")
    print(response.status_code, response.text or "deleted")
    return 0 if response.status_code < 300 else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--token", default=os.environ.get("QSTASH_TOKEN"))
    parser.add_argument("--qstash-url", default=os.environ.get("QSTASH_URL", DEFAULT_QSTASH_URL))
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create")
    p_create.add_argument("--base-url", required=True)
    p_create.add_argument("--cron", default="0 5 * * 1", help="default: every Monday 05:00 UTC")
    p_create.set_defaults(func=create)

    sub.add_parser("status").set_defaults(func=status)

    for name, fn in (("pause", pause), ("resume", resume), ("delete", delete)):
        p = sub.add_parser(name)
        p.add_argument("--schedule-id", required=True)
        p.set_defaults(func=fn)

    args = parser.parse_args()
    if not args.token:
        print("FAIL: no --token given and QSTASH_TOKEN is not set")
        return 1
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
