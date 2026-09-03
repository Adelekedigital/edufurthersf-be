import base64
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class CursorState:
    """Where a page request sits inside one logical search."""

    offset: int
    search_id: uuid.UUID


def _sign(value: str, secret: str) -> str:
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def encode_cursor(offset: int, filter_digest: str, search_id: uuid.UUID, secret: str) -> str:
    # Binding the cursor to the normalized filter digest prevents replaying a
    # cursor from one search against a different query. Carrying the logical
    # search id keeps every page of one search grouped under it, so paging does
    # not look like a series of separate searches.
    payload = json.dumps(
        {"offset": offset, "filter_digest": filter_digest, "search_id": str(search_id)},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(f"{payload}.{_sign(payload, secret)}".encode()).decode()


def decode_cursor(cursor: str, filter_digest: str, secret: str) -> CursorState:
    # Invalid cursors are deliberately indistinguishable from expired cursors;
    # do not expose signing or payload details to anonymous clients.
    try:
        token = base64.urlsafe_b64decode(cursor.encode()).decode()
        payload, signature = token.rsplit(".", 1)
        if not hmac.compare_digest(signature, _sign(payload, secret)):
            raise ValueError
        data = json.loads(payload)
        if (
            data["filter_digest"] != filter_digest
            or not isinstance(data["offset"], int)
            or data["offset"] < 0
        ):
            raise ValueError
        return CursorState(data["offset"], uuid.UUID(str(data["search_id"])))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid or expired search cursor") from exc
