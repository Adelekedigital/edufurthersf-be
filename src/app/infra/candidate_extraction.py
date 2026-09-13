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
from app.domain.extraction import extract_candidate_facts
from app.domain.models import Discovery
from app.infra.ai_router_client import AIRouterClient

logger = logging.getLogger("app.infra.candidate_extraction")

#: The Router's documented cap on `source_data` once serialized.
AI_ROUTER_SOURCE_DATA_MAX_BYTES = 16 * 1024


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
