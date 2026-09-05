import base64
import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

import httpx

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


@dataclass(frozen=True)
class QStashVerificationResult:
    """Verification outcome plus a stable reason code for operator logs.

    The reason never reaches the caller: a rejected delivery always gets a
    generic 401 so an unauthenticated client cannot probe the configuration.
    """

    ok: bool
    reason: str
    signed_destination: str | None = None


def decode_body_claim(value: str) -> bytes | None:
    """Return the raw digest from QStash's `body` claim.

    QStash sends the SHA-256 digest as base64. A 32-byte digest always carries
    one `=` of padding, and encoders differ on the URL-safe alphabet, so decode
    to bytes and compare digests rather than comparing encoded strings.
    """
    try:
        # urlsafe_b64decode maps -/_ onto +// first, so it accepts either
        # alphabet; a wrong-length result is rejected by the digest check.
        digest = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except ValueError:
        return None
    return digest if len(digest) == hashlib.sha256().digest_size else None


def publish_url(qstash_url: str) -> str:
    """Build the regional QStash publish endpoint from one configured host."""
    return f"{qstash_url.rstrip('/')}/v2/publish"


@dataclass(frozen=True)
class QStashPublisher:
    """Publish JSON jobs to the configured regional QStash endpoint."""

    qstash_url: str
    token: str

    async def publish(
        self, destination: str, body: dict[str, Any], deduplication_id: str | None = None
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        if deduplication_id:
            headers["Upstash-Deduplication-Id"] = deduplication_id
        url = f"{publish_url(self.qstash_url)}/{destination}"
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
            result = response.json()
        if not isinstance(result, dict):
            raise ValueError("QStash publish response must be an object")
        return result


class QStashVerifier:
    """Boundary for Core-compatible QStash signature verification.

    The production adapter must validate the raw body, issuer, destination,
    expiry/not-before, and current/next signing keys before dispatching a job.
    It fails closed until configured rather than accepting unsigned requests.
    """

    def __init__(self, config: QStashVerificationConfig) -> None:
        self.config = config

    def verify(self, *, raw_body: bytes, signature: str | None) -> QStashVerificationResult:
        # The destination comes from configuration, not from the reconstructed
        # request URL: behind a platform proxy the app sees the forwarded
        # http:// scheme and internal host, which never match the signed `sub`.
        destination = self.config.expected_destination
        if not (jwt and self.config.current_signing_key and self.config.next_signing_key):
            return QStashVerificationResult(False, "signing_keys_not_configured")
        if not destination:
            return QStashVerificationResult(False, "expected_destination_not_configured")
        if not signature:
            return QStashVerificationResult(False, "missing_upstash_signature_header")
        if not raw_body:
            return QStashVerificationResult(False, "empty_request_body")
        # Hash the exact raw body; re-serializing JSON can change its digest.
        expected_digest = hashlib.sha256(raw_body).digest()
        reason = "signature_not_issued_by_a_configured_signing_key"
        signed_destination: str | None = None
        for key in (self.config.current_signing_key, self.config.next_signing_key):
            try:
                claims = jwt.decode(
                    signature,
                    key,
                    algorithms=["HS256"],
                    options={"require": ["iss", "sub", "exp", "nbf", "body"]},
                )
            except jwt.ExpiredSignatureError:
                reason = "signature_expired"
                continue
            except jwt.ImmatureSignatureError:
                reason = "signature_not_yet_valid"
                continue
            except jwt.MissingRequiredClaimError:
                reason = "signature_missing_required_claim"
                continue
            except jwt.PyJWTError:
                continue
            if claims.get("iss") != "Upstash":
                reason = "unexpected_issuer"
                continue
            if claims.get("sub") != destination:
                reason = "destination_mismatch"
                signed_destination = str(claims.get("sub"))
                continue
            digest = decode_body_claim(str(claims.get("body", "")))
            if digest is None or not hmac.compare_digest(digest, expected_digest):
                reason = "body_hash_mismatch"
                continue
            return QStashVerificationResult(True, "verified")
        return QStashVerificationResult(False, reason, signed_destination)


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
        "sync_countries",
        "harvest_parsebot",
    }
)
