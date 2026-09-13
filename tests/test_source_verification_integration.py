"""fetch_and_verify_source - real-page fetch, deterministic re-extraction,
and agreement comparison against what a discovery originally reported.

`fetch_source`/`fetch_via_jina`/`try_ai_page_extraction` are monkeypatched at
their import sites in `source_verification.py`, matching
`test_source_persistence.py`'s convention: this module's own
fetch-precedence and agreement logic is under test, not a real network call.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import pytest
from sqlalchemy import select

from app.domain.models import Discovery, DiscoveryVerification, Source, SourcePage
from app.infra import source_verification as source_verification_module
from app.infra.source_fetch import FetchedSource
from app.infra.source_verification import fetch_and_verify_source
from tests.conftest import requires_db

pytestmark = requires_db


@dataclass(frozen=True)
class _FakeSettings:
    jina_api_key: str | None
    jina_monthly_call_limit: int = 500


async def _discovery(
    db, *, extracted_facts: dict | None, url: str = "https://example.test/a"
) -> tuple[Discovery, Source]:
    source = Source(
        name="Example Direct Source",
        source_type="official_direct",
        authority_grade="A",
        approved_domains=["example.test"],
        active=True,
    )
    db.add(source)
    await db.flush()
    page = SourcePage(source_id=source.source_id, normalized_url=url)
    db.add(page)
    await db.flush()
    discovery = Discovery(
        source_page_id=page.page_id,
        content_hash="hash-a",
        raw_title="Award A",
        raw_excerpt="details",
        extracted_facts=extracted_facts,
    )
    db.add(discovery)
    await db.commit()
    return discovery, source


def _stub_fetch_success(monkeypatch, *, status_code: int = 200, content: bytes = b"page text"):
    async def _fake(url, approved_domains, *, max_bytes=2_000_000):
        return FetchedSource(
            url=url, status_code=status_code, content=content, content_type="text/html"
        )

    monkeypatch.setattr(source_verification_module, "fetch_source", _fake)


def _stub_jina_success(monkeypatch, *, content: str = "page text"):
    calls: list[str] = []

    async def _fake(url, api_key, *, timeout_seconds=30.0):
        calls.append(url)
        return content

    monkeypatch.setattr(source_verification_module, "fetch_via_jina", _fake)
    return calls


def _stub_jina_never_called(monkeypatch):
    async def _fake(url, api_key, *, timeout_seconds=30.0):
        raise AssertionError("Jina should not have been called")

    monkeypatch.setattr(source_verification_module, "fetch_via_jina", _fake)


def _configure_jina(monkeypatch, *, api_key: str | None = "fake-jina-key", limit: int = 500):
    monkeypatch.setattr(
        source_verification_module, "get_settings", lambda: _FakeSettings(api_key, limit)
    )


def _stub_no_ai_page_extraction(monkeypatch):
    async def _fake(discovery, page_text):
        return None

    monkeypatch.setattr(source_verification_module, "try_ai_page_extraction", _fake)


def _stub_domain_approved(monkeypatch):
    """`validate_source_url`'s domain-allowlist check is exact-string, but
    its SSRF half does a real DNS lookup - `example.test` (RFC 2606) is
    guaranteed never to resolve, so tests that want the domain check to pass
    stub the whole function rather than depending on network access."""

    def _fake(url: str, approved_domains: list[str]) -> str:
        return url

    monkeypatch.setattr(source_verification_module, "validate_source_url", _fake)


async def test_domain_policy_rejection_never_calls_any_fetcher(db, monkeypatch) -> None:
    discovery, source = await _discovery(
        db, extracted_facts={"funding_mentions": ["£13,000"]}, url="https://not-approved.test/a"
    )
    _stub_jina_never_called(monkeypatch)
    _configure_jina(monkeypatch)
    _stub_no_ai_page_extraction(monkeypatch)

    with pytest.raises(ValueError, match="Source URL domain is not approved"):
        await fetch_and_verify_source(db, discovery, source)


async def test_jina_preferred_when_configured_and_records_agreement(db, monkeypatch) -> None:
    discovery, source = await _discovery(db, extracted_facts={"funding_mentions": ["£13,000"]})
    jina_calls = _stub_jina_success(monkeypatch, content="Awards a £13,000 grant this year.")
    _configure_jina(monkeypatch)
    _stub_domain_approved(monkeypatch)
    _stub_no_ai_page_extraction(monkeypatch)

    verification = await fetch_and_verify_source(db, discovery, source)

    assert jina_calls == ["https://example.test/a"]
    assert verification.fetch_method == "jina"
    assert verification.agreement["amount_matches"] is True
    assert verification.agreement["deadline_matches"] is None
    stored = await db.scalar(
        select(DiscoveryVerification).where(
            DiscoveryVerification.verification_id == verification.verification_id
        )
    )
    assert stored is not None
    assert stored.page_text == "Awards a £13,000 grant this year."


async def test_conflicting_amount_on_the_real_page_does_not_agree(db, monkeypatch) -> None:
    discovery, source = await _discovery(db, extracted_facts={"funding_mentions": ["£13,000"]})
    _stub_jina_success(monkeypatch, content="Awards a £16,750 grant this year.")
    _configure_jina(monkeypatch)
    _stub_domain_approved(monkeypatch)
    _stub_no_ai_page_extraction(monkeypatch)

    verification = await fetch_and_verify_source(db, discovery, source)

    assert verification.agreement["amount_matches"] is False


async def test_jina_unconfigured_falls_back_to_direct_fetch(db, monkeypatch) -> None:
    discovery, source = await _discovery(db, extracted_facts={"funding_mentions": ["£13,000"]})
    _stub_jina_never_called(monkeypatch)
    _configure_jina(monkeypatch, api_key=None)
    _stub_domain_approved(monkeypatch)
    _stub_fetch_success(monkeypatch, content=b"Awards a \xc2\xa313,000 grant.")
    _stub_no_ai_page_extraction(monkeypatch)

    verification = await fetch_and_verify_source(db, discovery, source)

    assert verification.fetch_method == "direct"
    assert verification.agreement["amount_matches"] is True


async def test_a_bad_direct_status_without_jina_raises(db, monkeypatch) -> None:
    discovery, source = await _discovery(db, extracted_facts={"funding_mentions": ["£13,000"]})
    _stub_jina_never_called(monkeypatch)
    _configure_jina(monkeypatch, api_key=None)
    _stub_domain_approved(monkeypatch)
    _stub_fetch_success(monkeypatch, status_code=404, content=b"not found")
    _stub_no_ai_page_extraction(monkeypatch)

    with pytest.raises(httpx.HTTPError):
        await fetch_and_verify_source(db, discovery, source)


async def test_own_facts_with_no_deadline_leave_deadline_agreement_not_applicable(
    db, monkeypatch
) -> None:
    discovery, source = await _discovery(db, extracted_facts={"funding_mentions": ["£13,000"]})
    _stub_jina_success(monkeypatch, content="Awards a £13,000 grant, deadline March 1, 2027.")
    _configure_jina(monkeypatch)
    _stub_domain_approved(monkeypatch)
    _stub_no_ai_page_extraction(monkeypatch)

    verification = await fetch_and_verify_source(db, discovery, source)

    assert verification.agreement["deadline_matches"] is None
