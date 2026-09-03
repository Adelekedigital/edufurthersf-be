"""Pagination cursors are signed, so they are an integrity boundary."""

from __future__ import annotations

import base64
import uuid

import pytest

from app.core.cursors import decode_cursor, encode_cursor

SECRET = "cursor-signing-secret"
DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64
SEARCH_ID = uuid.UUID("01a06530-b2f9-70f2-948b-728674a34193")


def test_a_cursor_round_trips() -> None:
    state = decode_cursor(encode_cursor(40, DIGEST, SEARCH_ID, SECRET), DIGEST, SECRET)
    assert state.offset == 40
    # The logical search survives paging, so pages are not counted as searches.
    assert state.search_id == SEARCH_ID


def test_a_cursor_is_bound_to_its_search_filters() -> None:
    """Replaying a cursor against different filters must not paginate them."""
    cursor = encode_cursor(20, DIGEST, SEARCH_ID, SECRET)
    with pytest.raises(ValueError):
        decode_cursor(cursor, OTHER_DIGEST, SECRET)


def test_a_cursor_signed_with_another_secret_is_refused() -> None:
    cursor = encode_cursor(20, DIGEST, SEARCH_ID, SECRET)
    with pytest.raises(ValueError):
        decode_cursor(cursor, DIGEST, "different-secret")


def test_a_tampered_offset_is_refused() -> None:
    forged = base64.urlsafe_b64encode(
        b'{"offset":999,"filter_digest":"'
        + DIGEST.encode()
        + b'","search_id":"'
        + str(SEARCH_ID).encode()
        + b'"}.deadbeef'
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
        decode_cursor(encode_cursor(1, DIGEST, SEARCH_ID, SECRET), DIGEST, "other")
    assert str(invalid.value) == str(wrong_secret.value)
