"""AI-Router-backed match explanations, cached per (cycle, searcher profile).

Built in from day one rather than added once repeat AI Router spend became a
problem: a cache hit costs nothing and answers instantly; a miss makes
exactly one real call. The explanation elaborates on an already-computed
`evaluate_match` decision - per the automation boundary, AI explains a
deterministic match, it never computes one - so a genuine failure anywhere
in this path (unconfigured, a non-`completed` outcome, a transport error)
degrades to "no explanation this time," the same way `extract_candidate`
degrades, never a failed request.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domain.ai_router import AIRouterOutcome, AIRouterRequest, AITask
from app.domain.matching import MatchDecision
from app.domain.models import MatchExplanation, ScholarshipCycle
from app.infra.ai_router_client import AIRouterClient
from app.infra.sessions import filter_digest

logger = logging.getLogger("app.infra.match_explanations")

#: This runs synchronously inside a user-facing request on a cache miss -
#: the router's default (DEFAULT_TIMEOUT_SECONDS, 45s) is a background-job
#: budget, not something to make a page wait on. A miss that blows this
#: bound still degrades to "no explanation," same as any other failure.
MATCH_EXPLANATION_TIMEOUT_SECONDS = 10.0


async def _cached(
    db: AsyncSession, *, cycle_id: uuid.UUID, profile_digest: str, facts_digest: str
) -> str | None:
    row = await db.scalar(
        select(MatchExplanation).where(
            MatchExplanation.cycle_id == cycle_id,
            MatchExplanation.profile_digest == profile_digest,
        )
    )
    if row is None or row.facts_digest != facts_digest:
        return None
    return row.explanation


async def _store(
    db: AsyncSession,
    *,
    cycle_id: uuid.UUID,
    profile_digest: str,
    facts_digest: str,
    explanation: str,
) -> None:
    stmt = insert(MatchExplanation).values(
        cycle_id=cycle_id,
        profile_digest=profile_digest,
        facts_digest=facts_digest,
        explanation=explanation,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["cycle_id", "profile_digest"],
        set_={"facts_digest": facts_digest, "explanation": explanation},
    )
    await db.execute(stmt)
    await db.commit()


async def get_match_explanation(
    db: AsyncSession,
    *,
    cycle: ScholarshipCycle,
    facts: dict[str, Any],
    origin_country: str,
    program_level: str,
    field: str | None,
    decision: MatchDecision,
) -> str | None:
    profile_payload = {
        "origin_country": origin_country,
        "program_level": program_level,
        "field": field,
    }
    profile_digest = filter_digest(profile_payload)
    facts_digest = filter_digest(facts)

    cached = await _cached(
        db, cycle_id=cycle.cycle_id, profile_digest=profile_digest, facts_digest=facts_digest
    )
    if cached is not None:
        return cached

    settings = get_settings()
    if not (
        settings.match_explanation_enabled
        and settings.ai_router_base_url
        and settings.ai_router_private_key_pem
        and settings.ai_router_key_id
    ):
        return None

    client = AIRouterClient(
        base_url=settings.ai_router_base_url,
        private_key_pem=settings.ai_router_private_key_pem,
        key_id=settings.ai_router_key_id,
        timeout_seconds=MATCH_EXPLANATION_TIMEOUT_SECONDS,
    )
    request = AIRouterRequest(
        task=AITask.match_explanation,
        task_version="v1",
        schema_version=1,
        product_id="scholarship_finder",
        feature_id="scholarship_detail",
        correlation_id=str(cycle.cycle_id),
        # Deterministic per (cycle, profile), not random per attempt - a
        # repeated cache-miss for the same pair must not double-spend budget.
        idempotency_key=f"match_explanation:{cycle.cycle_id}:{profile_digest}",
        source_data={
            "scholarship_name": cycle.scholarship.name if cycle.scholarship else "",
            "provider_name": cycle.scholarship.provider.name
            if cycle.scholarship and cycle.scholarship.provider
            else "",
            "facts": facts,
            "profile": profile_payload,
            "match_decision": {
                "fit": decision.fit,
                "reason_codes": list(decision.reason_codes),
                "caveats": list(decision.caveats),
            },
        },
    )
    try:
        response = await client.execute(request)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(
            "match_explanation_failed",
            extra={"cycle_id": str(cycle.cycle_id), "error": str(exc)},
        )
        return None
    if response.outcome != AIRouterOutcome.completed or not response.output:
        return None
    explanation = response.output.get("explanation")
    if not isinstance(explanation, str) or not explanation.strip():
        return None

    await _store(
        db,
        cycle_id=cycle.cycle_id,
        profile_digest=profile_digest,
        facts_digest=facts_digest,
        explanation=explanation,
    )
    return explanation
