"""Match a verified real page's hostname against an already-known Provider.

`decide_review`'s approve path requires a `provider_id`, but nothing in this
codebase resolves one automatically - a human reviewer picks it by hand
today. Auto-approve must fail closed here rather than ever creating a new
Provider on its own: a Provider's `approved_domains` is itself a vetted,
curated fact, not something to invent from a single fetch.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Provider


def _matches(hostname: str, approved_domains: list[str]) -> bool:
    allowed = {domain.lower().lstrip(".") for domain in approved_domains}
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in allowed)


async def resolve_provider_from_verified_url(
    db: AsyncSession, verified_url: str
) -> Provider | None:
    """`None` on zero or more-than-one match - ambiguous is the same as
    absent here, never resolved by guessing which Provider is "closer"."""
    hostname = urlsplit(verified_url).hostname or ""
    if not hostname:
        return None
    providers = list(await db.scalars(select(Provider)))
    matches = [p for p in providers if _matches(hostname, p.approved_domains)]
    if len(matches) != 1:
        return None
    return matches[0]
