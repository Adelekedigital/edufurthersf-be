"""Run the HTTP smoke checks required before a release.

These must exercise the endpoints the product actually depends on. Probing only
the unversioned health routes let a deployment whose search endpoint returned
500 still report three passing checks, so the search path is covered here even
though it writes an anonymous session row.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

SEARCH_PROBE: dict[str, Any] = {
    "origin_country": "NG",
    "program_level": "masters",
    "field": "public_health",
    "target_countries": ["CA", "GB"],
    "limit": 5,
}


def _check(name: str, response: httpx.Response) -> bool:
    if response.status_code != 200:
        print(f"FAIL {name}: HTTP {response.status_code} {response.text[:200]}")
        return False
    print(f"PASS {name}: HTTP 200")
    return True


def main() -> int:
    base_url = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8000").rstrip("/") + "/"
    try:
        with httpx.Client(base_url=base_url, timeout=10.0, follow_redirects=False) as client:
            for path in ("health", "ready", "api/v1/taxonomies"):
                if not _check(path, client.get(path)):
                    return 1

            search = client.post("api/v1/search", json=SEARCH_PROBE)
            if not _check("api/v1/search", search):
                return 1
            body = search.json()
            for key in ("data", "meta"):
                if key not in body:
                    print(f"FAIL api/v1/search: response is missing {key!r}")
                    return 1
            meta = body["meta"]
            print(
                f"     search_id={meta.get('search_id')} "
                f"results={len(body['data'])} "
                f"policy={meta.get('match_policy_version')}"
            )
            if meta.get("warnings"):
                print(f"     WARNINGS: {meta['warnings']}")

            # An empty index is a valid staging state, so only follow through to
            # the detail route when search actually returned something.
            if body["data"]:
                identifier = body["data"][0]["scholarship_id"]
                if not _check(
                    "api/v1/scholarships/{id}", client.get(f"api/v1/scholarships/{identifier}")
                ):
                    return 1
            else:
                print("SKIP api/v1/scholarships/{id}: no published records in this index")
    except httpx.HTTPError as exc:
        print(f"FAIL unable to reach {base_url}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
