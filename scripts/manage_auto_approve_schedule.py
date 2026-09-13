"""Create, pause, resume, inspect, or delete the hourly auto_approve_sweep
schedule on QStash.

The schedule delivers a static body to the app's stable `/internal/jobs`
callback on a cron cadence; `auto_approve_sweep`'s dedupe_key is recomputed
server-side per hour (see `RECURRING_HOURLY_KINDS` in `app/api/routes.py`)
so the same static body still produces a fresh, real run every hour rather
than being deduped against the first-ever delivery forever.

Creating this schedule is NOT the same as turning auto-approve on:
`Settings.auto_approve_enabled` (env var `AUTO_APPROVE_ENABLED`) must also be
`true` in the target environment, or every delivery is a harmless no-op
(`_auto_approve_sweep` checks the flag first, before anything else). This
script only controls whether the sweep runs at all - the app-level flag
controls whether it does anything once it does.

Usage (uv run python scripts/manage_auto_approve_schedule.py <command> ...):
    create --base-url https://your-app.example.com --token $env:QSTASH_TOKEN \\
        --cron "0 * * * *"   # every hour, on the hour
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
    body = {
        "kind": "auto_approve_sweep",
        "dedupe_key": "auto_approve_sweep:scheduled",
        "payload": {},
    }
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
    p_create.add_argument("--cron", default="0 * * * *", help="default: every hour, on the hour")
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
