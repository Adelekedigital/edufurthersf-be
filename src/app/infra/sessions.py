import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import AnonymousSession, Search


async def get_or_create_session(
    db: AsyncSession, response: Response, cookie: str | None
) -> AnonymousSession:
    session = None
    if cookie:
        try:
            session = await db.scalar(
                select(AnonymousSession).where(AnonymousSession.session_id == UUID(cookie))
            )
        except ValueError:
            session = None
    if session is None:
        session = AnonymousSession(
            pseudonymous_id=secrets.token_urlsafe(24),
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        db.add(session)
        await db.flush()
        response.set_cookie(
            "finder_session",
            str(session.session_id),
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=30 * 86400,
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
