"""Pagination cursors are signed, so they are an integrity boundary."""

from __future__ import annotations

import base64

import pytest

from app.core.cursors import decode_cursor, encode_cursor

SECRET = "cursor-signing-secret"
DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64


def test_a_cursor_round_trips() -> None:
    assert decode_cursor(encode_cursor(40, DIGEST, SECRET), DIGEST, SECRET) == 40


def test_a_cursor_is_bound_to_its_search_filters() -> None:
    """Replaying a cursor against different filters must not paginate them."""
    cursor = encode_cursor(20, DIGEST, SECRET)
    with pytest.raises(ValueError):
        decode_cursor(cursor, OTHER_DIGEST, SECRET)


def test_a_cursor_signed_with_another_secret_is_refused() -> None:
    cursor = encode_cursor(20, DIGEST, SECRET)
    with pytest.raises(ValueError):
        decode_cursor(cursor, DIGEST, "different-secret")


def test_a_tampered_offset_is_refused() -> None:
    forged = base64.urlsafe_b64encode(
        b'{"offset":999,"filter_digest":"' + DIGEST.encode() + b'"}.deadbeef'
    ).decode()
    with pytest.raises(ValueError):
        decode_cursor(forged, DIGEST, SECRET)


@pytest.mark.parametrize(
    "cursor",
    ["", "not-base64!!", base64.urlsafe_b64encode(b"no-signature").decode()],
)
def test_malformed_cursors_are_refused(cursor: str) -> None:
    with pytest.raises(ValueError):
        decode_cursor(cursor, DIGEST, SECRET)


def test_the_error_does_not_distinguish_invalid_from_expired() -> None:
    """Anonymous clients must not learn why a cursor failed."""
    with pytest.raises(ValueError) as invalid:
        decode_cursor("garbage", DIGEST, SECRET)
    with pytest.raises(ValueError) as wrong_secret:
        decode_cursor(encode_cursor(1, DIGEST, SECRET), DIGEST, "other")
    assert str(invalid.value) == str(wrong_secret.value)
