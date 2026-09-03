"""Run the safe, read-only HTTP smoke checks required before a release."""

from __future__ import annotations

import os
from urllib.parse import urljoin

import httpx


def main() -> int:
    base_url = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8000").rstrip("/") + "/"
    paths = ("health", "ready", "api/v1/taxonomies")
    try:
        with httpx.Client(base_url=base_url, timeout=5.0) as client:
            for path in paths:
                response = client.get(urljoin(base_url, path))
                if response.status_code != 200:
                    print(f"FAIL {path}: HTTP {response.status_code} {response.text[:200]}")
                    return 1
                print(f"PASS {path}: HTTP 200")
    except httpx.HTTPError as exc:
        print(f"FAIL unable to reach {base_url}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
