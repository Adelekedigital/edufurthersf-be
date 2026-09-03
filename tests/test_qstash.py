import base64
import hashlib
import time

import jwt

from app.infra.qstash import (
    QStashVerificationConfig,
    QStashVerifier,
    decode_body_claim,
    publish_url,
)

CURRENT_KEY = "current-signing-key-for-tests-0123456789"
NEXT_KEY = "next-signing-key-for-tests-0123456789"
DESTINATION = "https://api.example.com/api/v1/internal/jobs"
BODY = b'{"kind":"import_feed","dedupe_key":"feed-1","payload":{}}'


def _signature(
    key: str = CURRENT_KEY, *, sub: str = DESTINATION, body: bytes = BODY, pad: bool = True
) -> str:
    encoded = base64.urlsafe_b64encode(hashlib.sha256(body).digest()).decode()
    body_hash = encoded if pad else encoded.rstrip("=")
    now = int(time.time())
    return jwt.encode(
        {
            "iss": "Upstash",
            "sub": sub,
            "exp": now + 300,
            "nbf": now - 10,
            "iat": now,
            "body": body_hash,
        },
        key,
        algorithm="HS256",
    )


def _verifier() -> QStashVerifier:
    return QStashVerifier(QStashVerificationConfig(CURRENT_KEY, NEXT_KEY, DESTINATION))


def test_qstash_verifier_accepts_current_signing_key() -> None:
    assert _verifier().verify(raw_body=BODY, signature=_signature()).ok


def test_qstash_verifier_accepts_next_signing_key_during_rotation() -> None:
    assert _verifier().verify(raw_body=BODY, signature=_signature(NEXT_KEY)).ok


def test_qstash_verifier_rejects_signature_for_another_destination() -> None:
    other = _signature(sub="https://api.example.com/api/v1/internal/jobs/import_feed")
    assert not _verifier().verify(raw_body=BODY, signature=other).ok


def test_qstash_verifier_rejects_tampered_body() -> None:
    assert not _verifier().verify(raw_body=BODY + b" ", signature=_signature()).ok


def test_qstash_verifier_rejects_unknown_signing_key() -> None:
    assert not _verifier().verify(raw_body=BODY, signature=_signature("attacker-key")).ok


def test_qstash_verifier_fails_closed_when_unconfigured() -> None:
    verifier = QStashVerifier(QStashVerificationConfig(None, None, DESTINATION))
    assert not verifier.verify(raw_body=BODY, signature=_signature()).ok


def test_qstash_verifier_fails_closed_without_a_destination() -> None:
    verifier = QStashVerifier(QStashVerificationConfig(CURRENT_KEY, NEXT_KEY, ""))
    assert not verifier.verify(raw_body=BODY, signature=_signature()).ok


def test_qstash_publish_url_uses_configured_region() -> None:
    assert (
        publish_url("https://qstash-us-east-1.upstash.io/")
        == "https://qstash-us-east-1.upstash.io/v2/publish"
    )


def test_qstash_verifier_accepts_the_padded_body_claim_qstash_actually_sends() -> None:
    # A SHA-256 digest always base64-encodes with one "=" of padding, and
    # QStash sends it that way; comparing encoded strings rejected every job.
    result = _verifier().verify(raw_body=BODY, signature=_signature(pad=True))
    assert result.ok, result.reason


def test_qstash_verifier_accepts_an_unpadded_body_claim() -> None:
    assert _verifier().verify(raw_body=BODY, signature=_signature(pad=False)).ok


def test_qstash_verifier_reports_why_a_delivery_was_rejected() -> None:
    other = _signature(sub="https://api.example.com/api/v1/internal/jobs/import_feed")
    result = _verifier().verify(raw_body=BODY, signature=other)
    assert not result.ok
    assert result.reason == "destination_mismatch"
    assert result.signed_destination == "https://api.example.com/api/v1/internal/jobs/import_feed"


def test_qstash_verifier_reports_a_missing_signature_header() -> None:
    assert _verifier().verify(raw_body=BODY, signature=None).reason == (
        "missing_upstash_signature_header"
    )


def test_body_claim_decodes_both_base64_alphabets() -> None:
    digest = hashlib.sha256(BODY).digest()
    assert decode_body_claim(base64.urlsafe_b64encode(digest).decode()) == digest
    assert decode_body_claim(base64.b64encode(digest).decode()) == digest
    assert decode_body_claim("not-a-digest") is None
