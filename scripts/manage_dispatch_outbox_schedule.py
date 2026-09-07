"""Create, pause, resume, inspect, or delete the outbox-dispatch schedule on
QStash.

`dispatch_analytics_events` (app/infra/outbox.py) is naturally idempotent -
it claims a bounded batch with SKIP LOCKED and no-ops when nothing is
pending - so unlike the freshness jobs this needs no per-tick dedupe_key
scheme; a fixed cron plus QStash's own redelivery handling is enough.

Usage (uv run python scripts/manage_dispatch_outbox_schedule.py <command> ...):
    create --base-url https://your-app.example.com --token $env:QSTASH_TOKEN \\
        --cron "*/2 * * * *"   # every 2 minutes
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
    body = {"kind": "dispatch_outbox", "dedupe_key": "dispatch_outbox:scheduled", "payload": {}}
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
    p_create.add_argument("--cron", default="*/2 * * * *", help="default: every 2 minutes")
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
