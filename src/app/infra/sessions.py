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


async def record_search(db: AsyncSession, session: AnonymousSession, filters: dict) -> UUID:
    serialized = json.dumps(filters, sort_keys=True, separators=(",", ":"))
    search = Search(
        session_id=session.session_id,
        filter_digest=hashlib.sha256(serialized.encode()).hexdigest(),
        filters=filters,
    )
    db.add(search)
    await db.flush()
    return search.search_id
