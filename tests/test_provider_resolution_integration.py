"""resolve_provider_from_verified_url - fails closed on zero or ambiguous
matches; never creates a Provider."""

from __future__ import annotations

from app.domain.models import Provider
from app.infra.provider_resolution import resolve_provider_from_verified_url
from tests.conftest import requires_db

pytestmark = requires_db


async def _provider(db, *, name: str, approved_domains: list[str]) -> Provider:
    provider = Provider(name=name, approved_domains=approved_domains)
    db.add(provider)
    await db.commit()
    return provider


async def test_an_exact_hostname_match_resolves(db) -> None:
    provider = await _provider(db, name="UCL", approved_domains=["ucl.ac.uk"])

    resolved = await resolve_provider_from_verified_url(db, "https://ucl.ac.uk/scholarships/award")

    assert resolved is not None
    assert resolved.provider_id == provider.provider_id


async def test_a_subdomain_of_an_approved_domain_resolves(db) -> None:
    provider = await _provider(db, name="UCL", approved_domains=["ucl.ac.uk"])

    resolved = await resolve_provider_from_verified_url(db, "https://apply.ucl.ac.uk/award")

    assert resolved is not None
    assert resolved.provider_id == provider.provider_id


async def test_no_matching_provider_returns_none(db) -> None:
    await _provider(db, name="UCL", approved_domains=["ucl.ac.uk"])

    resolved = await resolve_provider_from_verified_url(db, "https://unrelated.test/award")

    assert resolved is None


async def test_two_matching_providers_is_ambiguous(db) -> None:
    """Never resolved by guessing which provider is "closer" - a bad
    approved_domains configuration must fail closed, not pick one."""
    await _provider(db, name="A", approved_domains=["university.test"])
    await _provider(db, name="B", approved_domains=["university.test"])

    resolved = await resolve_provider_from_verified_url(db, "https://university.test/award")

    assert resolved is None


async def test_a_url_with_no_hostname_returns_none(db) -> None:
    await _provider(db, name="UCL", approved_domains=["ucl.ac.uk"])

    resolved = await resolve_provider_from_verified_url(db, "not-a-url")

    assert resolved is None
