import base64
import hashlib
from dataclasses import dataclass
from typing import Any

_jwt: Any = None
try:
    import jwt as _jwt
except ImportError:  # pragma: no cover - dependency is declared in pyproject
    pass

jwt: Any = _jwt


@dataclass(frozen=True)
class QStashVerificationConfig:
    current_signing_key: str | None
    next_signing_key: str | None
    expected_destination: str


def publish_url(qstash_url: str) -> str:
    """Build the regional QStash publish endpoint from one configured host."""
    return f"{qstash_url.rstrip('/')}/v2/publish"


class QStashVerifier:
    """Boundary for Core-compatible QStash signature verification.

    The production adapter must validate the raw body, issuer, destination,
    expiry/not-before, and current/next signing keys before dispatching a job.
    It fails closed until configured rather than accepting unsigned requests.
    """

    def __init__(self, config: QStashVerificationConfig) -> None:
        self.config = config

    def verify(self, *, raw_body: bytes, signature: str | None, destination: str) -> bool:
        # Verify the exact raw body; re-serializing JSON can change its hash.
        if not (
            jwt
            and self.config.current_signing_key
            and self.config.next_signing_key
            and signature
            and raw_body
        ):
            return False
        if destination != self.config.expected_destination:
            return False
        # QStash encodes the SHA-256 digest as URL-safe base64 in `body`.
        body_hash = base64.urlsafe_b64encode(hashlib.sha256(raw_body).digest()).decode().rstrip("=")
        for key in (self.config.current_signing_key, self.config.next_signing_key):
            try:
                claims = jwt.decode(
                    signature,
                    key,
                    algorithms=["HS256"],
                    options={"require": ["iss", "sub", "exp", "nbf", "body"]},
                )
                if (
                    claims.get("iss") == "Upstash"
                    and claims.get("sub") == destination
                    and claims.get("body") == body_hash
                ):
                    return True
            except jwt.PyJWTError:
                continue
        return False


ALLOWED_JOB_KINDS = frozenset(
    {
        "import_feed",
        "fetch_source_page",
        "normalize_discovery",
        "link_canonical",
        "extract_candidate",
        "prepare_review",
        "refresh_status",
        "reverify_due",
        "dispatch_outbox",
        "reconcile_stuck_jobs",
    }
)
