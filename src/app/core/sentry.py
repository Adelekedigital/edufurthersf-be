import re
from typing import Any, cast

_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
# Substrings, not exact names: this service authenticates with the custom
# headers X-Service-Token and Upstash-Signature, which an exact-match list of
# well-known header names does not cover, and neither does sentry-sdk's own
# default filter.
_SECRET_MARKERS = (
    "authorization",
    "cookie",
    "token",
    "password",
    "secret",
    "signature",
    "api-key",
    "apikey",
    "credential",
)


def _is_secret_key(key: str) -> bool:
    return any(marker in key.lower() for marker in _SECRET_MARKERS)


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[Filtered]" if _is_secret_key(str(key)) else _scrub(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    if isinstance(value, str):
        return _EMAIL.sub("[email]", value)
    return value


def scrub_event(event: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """Remove credentials and direct email addresses before Sentry transport."""
    scrubbed = _scrub(event)
    if hint:
        scrubbed["extra"] = _scrub(hint.get("data", {}))
    return scrubbed


def initialize_sentry(
    dsn: str | None, environment: str, release: str, traces_sample_rate: float
) -> None:
    if not dsn:
        return
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        traces_sample_rate=traces_sample_rate,
        send_default_pii=False,
        # Frame locals would otherwise carry the signing keys compared inside
        # QStashVerifier.verify and the expected internal service token.
        include_local_variables=False,
        before_send=cast(Any, scrub_event),
        integrations=[FastApiIntegration()],
    )
