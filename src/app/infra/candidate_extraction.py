"""Shared candidate-fact extraction: deterministic regex extraction plus a
best-effort AI Router pass.

Used both by the standalone `extract_candidate` job (on-demand/backfill
re-extraction, `infra/worker.py`) and inline by `link_discovery`
(`infra/linking.py`) - `extract_candidate` was never actually wired into
the ingestion pipeline (`import_feed_records` only ever enqueues
`normalize_discovery`/`link_canonical`), so `link_discovery` populates
these facts itself now, before a ReviewTask's priority is computed from
them, rather than depending on a separately-scheduled job with no
ordering guarantee relative to when the ReviewTask is created.
"""

from __future__ import annotations

import logging

import httpx

from app.core.config import get_settings
from app.domain.ai_router import AIRouterOutcome, AIRouterRequest, AITask
from app.domain.extraction import (
    CURRENCY_AMOUNT_PATTERN,
    MONTH_NAME_DATE_PATTERN,
    extract_candidate_facts,
)
from app.domain.models import Discovery
from app.infra.ai_router_client import AIRouterClient

logger = logging.getLogger("app.infra.candidate_extraction")

#: The Router's documented cap on `source_data` once serialized.
AI_ROUTER_SOURCE_DATA_MAX_BYTES = 16 * 1024
#: A real fetched page is usually far larger than a feed excerpt - the same
#: cap applies, but see `_window_page_text` for how it's spent.
AI_ROUTER_PAGE_DATA_MAX_BYTES = 16 * 1024
#: Characters of surrounding context kept around each regex hit when
#: windowing a real page - enough for a reader (human or model) to see the
#: sentence a figure or date sits in, not just the bare digits.
_WINDOW_CONTEXT_CHARS = 150


async def try_ai_extraction(discovery: Discovery) -> dict | None:
    """A best-effort AI Router pass, layered on top of the deterministic
    extraction below - never required for a caller to succeed. Unconfigured,
    a non-`completed` outcome, or a transport failure all just mean no
    AI-assisted facts this time, same as if the router did not exist.
    """
    settings = get_settings()
    if not (
        settings.ai_router_base_url
        and settings.ai_router_private_key_pem
        and settings.ai_router_key_id
    ):
        return None
    excerpt = discovery.raw_excerpt or ""
    if len(excerpt.encode()) > AI_ROUTER_SOURCE_DATA_MAX_BYTES:
        excerpt = excerpt.encode()[:AI_ROUTER_SOURCE_DATA_MAX_BYTES].decode(errors="ignore")
    client = AIRouterClient(
        base_url=settings.ai_router_base_url,
        private_key_pem=settings.ai_router_private_key_pem,
        key_id=settings.ai_router_key_id,
    )
    request = AIRouterRequest(
        task=AITask.scholarship_extraction,
        task_version="v1",
        schema_version=1,
        product_id="scholarship_finder",
        feature_id="extract_candidate",
        correlation_id=str(discovery.discovery_id),
        # Deterministic per discovery, not random per attempt - a retried
        # extraction must not double-spend the shared budget.
        idempotency_key=f"extract_candidate:{discovery.discovery_id}",
        source_data={"raw_title": discovery.raw_title, "raw_excerpt": excerpt},
    )
    try:
        response = await client.execute(request)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(
            "ai_router_extraction_failed",
            extra={"discovery_id": str(discovery.discovery_id), "error": str(exc)},
        )
        return None
    if response.outcome != AIRouterOutcome.completed:
        return None
    return response.output


async def extract_and_store_facts(discovery: Discovery, *, include_ai: bool = True) -> None:
    """Populate `discovery.extracted_facts`/`ai_extracted_facts` in place.

    Never commits itself - composes cleanly inside a larger transaction
    (`link_discovery`) as well as standalone (the `extract_candidate` job).

    `include_ai=False` for `duplicate_pending` discoveries (see
    `infra/linking.py`): a duplicate never gets its own reviewer, so an AI
    Router call there would be spent on a result nobody looks at - but the
    deterministic facts are still worth having, for corroboration.
    """
    discovery.extracted_facts = extract_candidate_facts(discovery.raw_title, discovery.raw_excerpt)
    discovery.ai_extracted_facts = await try_ai_extraction(discovery) if include_ai else None


def _window_page_text(page_text: str, *, max_bytes: int = AI_ROUTER_PAGE_DATA_MAX_BYTES) -> str:
    """Cut a real fetched page down to the Router's size cap around whatever
    looks like a funding figure or a deadline, instead of blindly truncating
    from the start - the relevant sentence on an official page is rarely in
    the first few KB. Falls back to a head truncation when nothing matches,
    which is itself useful signal (a page with no regex-matchable amount or
    date at all is one `run_sanity_checks` will likely fail anyway)."""
    matches = sorted(
        (m.start(), m.end())
        for pattern in (CURRENCY_AMOUNT_PATTERN, MONTH_NAME_DATE_PATTERN)
        for m in pattern.finditer(page_text)
    )
    if not matches:
        return page_text.encode()[:max_bytes].decode(errors="ignore")

    windows: list[tuple[int, int]] = []
    for start, end in matches:
        window_start = max(0, start - _WINDOW_CONTEXT_CHARS)
        window_end = min(len(page_text), end + _WINDOW_CONTEXT_CHARS)
        if windows and window_start <= windows[-1][1]:
            windows[-1] = (windows[-1][0], max(windows[-1][1], window_end))
        else:
            windows.append((window_start, window_end))

    windowed = " ... ".join(page_text[start:end] for start, end in windows)
    return windowed.encode()[:max_bytes].decode(errors="ignore")


async def try_ai_page_extraction(discovery: Discovery, page_text: str) -> dict | None:
    """A second, distinct AI Router pass over a real fetched page - never an
    extension of `try_ai_extraction`, which is shaped and sized around the
    short feed excerpt. Kept purely as supplementary evidence for a human
    auditing an auto-approval later: the actual pass/fail agreement check
    against `discovery.extracted_facts` is computed deterministically (see
    `infra/source_verification.py`), never by asking the model whether it
    "agrees" - that would be asking it to verify, which crosses the same
    automation boundary `try_ai_extraction` already respects.
    """
    settings = get_settings()
    if not (
        settings.ai_router_base_url
        and settings.ai_router_private_key_pem
        and settings.ai_router_key_id
    ):
        return None
    client = AIRouterClient(
        base_url=settings.ai_router_base_url,
        private_key_pem=settings.ai_router_private_key_pem,
        key_id=settings.ai_router_key_id,
    )
    request = AIRouterRequest(
        task=AITask.scholarship_extraction,
        task_version="v1",
        schema_version=1,
        product_id="scholarship_finder",
        feature_id="verify_candidate",
        correlation_id=str(discovery.discovery_id),
        idempotency_key=f"verify_candidate:{discovery.discovery_id}",
        source_data={"raw_title": discovery.raw_title, "page_text": _window_page_text(page_text)},
    )
    try:
        response = await client.execute(request)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(
            "ai_router_page_verification_failed",
            extra={"discovery_id": str(discovery.discovery_id), "error": str(exc)},
        )
        return None
    if response.outcome != AIRouterOutcome.completed:
        return None
    return response.output
