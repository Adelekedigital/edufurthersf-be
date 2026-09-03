import re
from typing import Any, cast

_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_SECRET_KEYS = {"authorization", "cookie", "set-cookie", "token", "password", "secret"}


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[Filtered]" if key.lower() in _SECRET_KEYS else _scrub(item)
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
        before_send=cast(Any, scrub_event),
        integrations=[FastApiIntegration()],
    )
