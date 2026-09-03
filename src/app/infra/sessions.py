import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import AnonymousSession, Search

SESSION_COOKIE = "finder_session"
SESSION_TTL = timedelta(days=30)


async def get_or_create_session(
    db: AsyncSession, response: Response, cookie: str | None
) -> AnonymousSession:
    """Resolve the caller's session from an unguessable bearer token.

    The cookie carries `pseudonymous_id`, never the primary key: a session id
    appears in URLs, logs and Core handoff payloads, and UUIDv7 is
    time-ordered, so treating it as a credential would let one visitor adopt
    another's session and the searches attached to it.
    """
    session = None
    if cookie:
        session = await db.scalar(
            select(AnonymousSession).where(
                AnonymousSession.pseudonymous_id == cookie,
                AnonymousSession.expires_at > datetime.now(UTC),
            )
        )
    if session is None:
        session = AnonymousSession(
            pseudonymous_id=secrets.token_urlsafe(32),
            expires_at=datetime.now(UTC) + SESSION_TTL,
        )
        db.add(session)
        await db.flush()
        response.set_cookie(
            SESSION_COOKIE,
            session.pseudonymous_id,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=int(SESSION_TTL.total_seconds()),
        )
    return session


SEARCH_RETENTION = timedelta(days=30)


async def record_search_response(
    db: AsyncSession,
    *,
    session: AnonymousSession | None,
    search_id: UUID,
    filters: dict,
    filter_digest: str,
    snapshot: dict,
    evaluated_at: datetime,
    page_number: int,
    requested_limit: int,
    returned_count: int,
    total_match_count: int,
    duration_ms: int,
) -> Search:
    """Persist one evaluated response page of a logical search.

    Re-requesting a page rewrites that page's row rather than adding another,
    so a retry cannot manufacture extra history, while a different page of the
    same search is a separate row.
    """
    existing = await db.scalar(
        select(Search).where(Search.search_id == search_id, Search.page_number == page_number)
    )
    search = existing or Search(search_id=search_id, page_number=page_number)
    search.session_id = session.session_id if session else None
    search.filters = filters
    search.filter_digest = filter_digest
    search.result_snapshot = snapshot
    search.snapshot_schema_version = str(snapshot.get("schema_version", "snapshot-v1"))
    search.match_policy_version = str(snapshot["meta"]["match_policy_version"])
    search.taxonomy_version = str(snapshot["meta"]["taxonomy_version"])
    search.requested_limit = requested_limit
    search.returned_count = returned_count
    search.total_match_count = total_match_count
    search.duration_ms = duration_ms
    search.evaluated_at = evaluated_at
    search.expires_at = evaluated_at + SEARCH_RETENTION
    if existing is None:
        db.add(search)
    await db.flush()
    return search


def filter_digest(filters: dict) -> str:
    serialized = json.dumps(filters, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()
