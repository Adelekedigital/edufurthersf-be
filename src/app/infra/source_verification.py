"""Fetch a discovery's own real page and check whether it agrees with what
was originally reported - the evidence-grounded half of auto-approval
(`docs/candidate-verification-standard.md`'s "a real official source was
actually fetched and read" bar, not just cited by an aggregator).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domain.extraction import extract_candidate_facts
from app.domain.fact_matching import amounts_match, deadlines_match
from app.domain.models import Discovery, DiscoveryVerification, Source, SourcePage
from app.infra.candidate_extraction import try_ai_page_extraction
from app.infra.jina_client import fetch_via_jina
from app.infra.research_budget import reserve_call
from app.infra.source_fetch import fetch_source, validate_source_url

logger = logging.getLogger("app.infra.source_verification")


async def fetch_and_verify_source(
    db: AsyncSession, discovery: Discovery, source: Source
) -> DiscoveryVerification:
    """Fetch, re-extract deterministically, and persist the result.

    Raises `ValueError` for a domain-policy violation or an unfetchable page,
    and `httpx.HTTPError` for a transport failure reaching either fetch
    method - callers treat both the same way: verification failed, the
    candidate stays with a human, never a best-effort pass.
    """
    url = await _resolve_url(db, discovery)
    # A policy decision, not a reachability problem - checked unconditionally
    # here (unlike source_persistence.py's failure-triggered Jina fallback,
    # which inherits an already-validated URL) because Jina is tried first
    # for verification, so nothing else would ever check this domain.
    validate_source_url(url, source.approved_domains)
    page_text, fetch_method = await _fetch_page_text(db, url, source.approved_domains)

    real_page_facts = extract_candidate_facts(None, page_text)
    ai_reextracted_facts = await try_ai_page_extraction(discovery, page_text)
    agreement = _compare_facts(discovery.extracted_facts, real_page_facts)

    verification = DiscoveryVerification(
        discovery_id=discovery.discovery_id,
        fetched_url=url,
        fetch_method=fetch_method,
        page_text=page_text,
        ai_reextracted_facts=ai_reextracted_facts,
        agreement=agreement,
    )
    db.add(verification)
    await db.commit()
    return verification


async def _resolve_url(db: AsyncSession, discovery: Discovery) -> str:
    row = (
        await db.execute(
            select(SourcePage.normalized_url, SourcePage.final_url).where(
                SourcePage.page_id == discovery.source_page_id
            )
        )
    ).one()
    normalized_url, final_url = row
    return final_url or normalized_url


async def _fetch_page_text(
    db: AsyncSession, url: str, approved_domains: list[str]
) -> tuple[str, str]:
    """Prefer Jina's Reader - clean text, and this repo has no HTML-to-text
    library - falling back to the raw direct fetch (uncleaned HTML, tagged as
    such) only when Jina is unconfigured or its own budget is exhausted.
    Reverse precedence from `source_persistence.py`'s failure-triggered
    fallback, deliberately: verification specifically wants clean text over
    a merely-reachable one, not just a resilient path to *some* content.
    """
    settings = get_settings()
    if settings.jina_api_key:
        allowed = await reserve_call(db, "jina", settings.jina_monthly_call_limit)
        if allowed:
            try:
                return await fetch_via_jina(url, settings.jina_api_key), "jina"
            except httpx.HTTPError as exc:
                logger.warning(
                    "jina_verification_fetch_failed", extra={"url": url, "error": str(exc)}
                )
    fetched = await fetch_source(url, approved_domains)
    if fetched.status_code >= 400:
        raise httpx.HTTPError(f"page fetch returned status {fetched.status_code}")
    return fetched.content.decode(errors="ignore"), "direct"


def _compare_facts(
    own_facts: dict[str, Any] | None, real_page_facts: dict[str, Any]
) -> dict[str, Any]:
    own_amounts = (own_facts or {}).get("funding_mentions") or []
    own_deadlines = (own_facts or {}).get("deadline_mentions") or []
    page_amounts = real_page_facts.get("funding_mentions") or []
    page_deadlines = real_page_facts.get("deadline_mentions") or []

    # None (not applicable) when the discovery itself asserts no amount/deadline -
    # same convention as domain/corroboration.py's amount_corroborated/deadline_corroborated.
    amount_matches = (
        None
        if not own_amounts
        else any(amounts_match(a, b) for a in own_amounts for b in page_amounts)
    )
    deadline_matches = (
        None
        if not own_deadlines
        else any(deadlines_match(a, b) for a in own_deadlines for b in page_deadlines)
    )
    return {"amount_matches": amount_matches, "deadline_matches": deadline_matches}
