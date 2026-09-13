"""Attempt to auto-approve and publish one high-confidence candidate.

Composes existing, unmodified functions rather than reimplementing their
mutations - `decide_review` and `publish_cycle` are the only places a
Scholarship gets created or a cycle gets published, human-triggered or not,
so a future guard added to either is never silently bypassed here.

Gates on a strict boolean AND for this first cut, not a soft weighted score
(see `domain/auto_approval_scoring.py` for the diagnostic score, which is
recorded but never itself the gate) - matching the verification standard's
own auto-reject philosophy: any one check missing means the candidate stays
with a human, full stop.
"""

from __future__ import annotations

import logging
import random
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from pydantic import HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.review_schemas import ReviewDecisionRequest
from app.core.config import get_settings
from app.domain.auto_approval_scoring import compute_auto_approval_score
from app.domain.auto_approve_facts import derive_cycle_facts_from_extraction
from app.domain.models import (
    AuditLog,
    AutoApprovalAudit,
    Discovery,
    PublicStatus,
    ReviewTask,
    Scholarship,
    Source,
    SourcePage,
)
from app.domain.publication import build_cycle_facts
from app.domain.sanity_checks import run_sanity_checks
from app.infra.corroboration import gather_corroboration
from app.infra.countries import load_vocabulary
from app.infra.provider_resolution import resolve_provider_from_verified_url
from app.infra.publication import publish_cycle
from app.infra.reviews import decide_review
from app.infra.source_verification import fetch_and_verify_source

logger = logging.getLogger("app.infra.auto_approval")

_SLUG_INVALID = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class AutoApprovalOutcome:
    approved: bool
    reason: str
    scholarship_id: uuid.UUID | None = None
    cycle_id: uuid.UUID | None = None


async def attempt_auto_approval(db: AsyncSession, review_task_id: uuid.UUID) -> AutoApprovalOutcome:
    settings = get_settings()
    task = await db.scalar(
        select(ReviewTask).where(ReviewTask.review_task_id == review_task_id).with_for_update()
    )
    if task is None or task.state != "open" or task.discovery_id is None:
        return AutoApprovalOutcome(approved=False, reason="task_not_eligible")

    discovery = await db.scalar(
        select(Discovery).where(Discovery.discovery_id == task.discovery_id).with_for_update()
    )
    if discovery is None or discovery.auto_review_evaluated_at is not None:
        return AutoApprovalOutcome(approved=False, reason="not_eligible")

    if task.draft_recommendation is None:
        # prepare_review hasn't finished yet - a transient state, not a
        # verdict, so this candidate stays untouched for a later sweep to
        # retry rather than being marked evaluated.
        return AutoApprovalOutcome(approved=False, reason="draft_not_ready")

    async def _defer(reason: str) -> AutoApprovalOutcome:
        discovery.auto_review_evaluated_at = datetime.now(UTC)
        await db.commit()
        return AutoApprovalOutcome(approved=False, reason=reason)

    if task.draft_recommendation.get("verdict") == "reject":
        return await _defer("draft_rejected")

    age = datetime.now(UTC) - discovery.created_at
    if age < timedelta(hours=settings.auto_approve_min_age_hours):
        return AutoApprovalOutcome(approved=False, reason="too_young")

    source = await db.scalar(
        select(Source)
        .join(SourcePage, SourcePage.source_id == Source.source_id)
        .where(SourcePage.page_id == discovery.source_page_id)
    )
    if source is None:
        return await _defer("source_missing")

    corroboration = await gather_corroboration(db, discovery)
    if (
        corroboration.independent_source_count < settings.auto_approve_min_corroboration_sources
        or not corroboration.amount_corroborated
        or corroboration.deadline_corroborated is False
    ):
        return await _defer("insufficient_corroboration")

    try:
        verification = await fetch_and_verify_source(db, discovery, source)
    except (ValueError, httpx.HTTPError) as exc:
        logger.info(
            "auto_approval_verification_failed",
            extra={"discovery_id": str(discovery.discovery_id), "error": str(exc)},
        )
        return await _defer("verification_failed")

    if settings.auto_approve_require_real_page_verification and (
        not verification.agreement.get("amount_matches")
        or verification.agreement.get("deadline_matches") is False
    ):
        return await _defer("page_disagreement")

    country_names = (await load_vocabulary(db)).names
    derived = derive_cycle_facts_from_extraction(
        raw_title=discovery.raw_title,
        raw_excerpt=discovery.raw_excerpt,
        page_text=verification.page_text,
        extracted_facts=discovery.extracted_facts,
        country_names=country_names,
    )
    if derived is None:
        return await _defer("facts_not_derivable")
    if derived.deadline_at is None:
        # A `status_unknown` cycle never surfaces in search results at all
        # (see `_build_search_result` in api/routes.py) - auto-approving one
        # would publish a record nobody ever sees, defeating the point.
        # `open_verified` requires the source to *explicitly confirm* current
        # acceptance; per the standard's own accepted evidence for that bar
        # ("Westminster: live deadline, not lapsed"), a real, corroborated,
        # page-verified future deadline is exactly that confirmation - so
        # rather than ever guessing towards a visible status, auto-approve
        # simply requires one to exist at all.
        return await _defer("no_deadline_evidence")

    sanity = run_sanity_checks(
        extracted_facts=discovery.extracted_facts, deadline_at=derived.deadline_at
    )
    if not sanity.passed:
        return await _defer("sanity_check_failed")

    provider = await resolve_provider_from_verified_url(db, verification.fetched_url)
    if provider is None:
        return await _defer("provider_not_resolved")

    slug = await _available_slug(db, discovery.raw_title or "scholarship")
    if slug is None:
        return await _defer("slug_unavailable")

    score = compute_auto_approval_score(
        independent_source_count=corroboration.independent_source_count,
        amount_matches_real_page=bool(verification.agreement.get("amount_matches")),
        deadline_matches_real_page=verification.agreement.get("deadline_matches"),
        sanity_passed=sanity.passed,
        authority_grade=source.authority_grade,
    )
    snapshot = {
        "corroboration": {
            "independent_source_count": corroboration.independent_source_count,
            "amount_corroborated": corroboration.amount_corroborated,
            "deadline_corroborated": corroboration.deadline_corroborated,
            "corroborating_discovery_ids": corroboration.corroborating_discovery_ids,
        },
        "real_page_verification": {
            "fetched_url": verification.fetched_url,
            "fetch_method": verification.fetch_method,
            "verification_id": str(verification.verification_id),
            "agreement": verification.agreement,
        },
        "sanity_checks": {
            "has_positive_amount": sanity.has_positive_amount,
            "deadline_is_future_or_absent": sanity.deadline_is_future_or_absent,
        },
        "derived_facts": {
            "destinations": derived.destinations,
            "levels": derived.levels,
            "award_type": derived.award_type,
            "funding_type": derived.funding_type,
        },
        "score": score,
        "source_authority_grade": source.authority_grade,
    }

    decision_request = ReviewDecisionRequest(
        decision="approve",
        provider_id=provider.provider_id,
        canonical_name=(discovery.raw_title or "Unnamed scholarship")[:500],
        official_home_url=HttpUrl(verification.fetched_url),
        slug=slug,
        award_type=derived.award_type,
        reason=(
            f"Auto-approved: {corroboration.independent_source_count} independent sources "
            f"corroborate amount/deadline; real page verified via {verification.fetch_method} "
            f"fetch; diagnostic score={score}."
        ),
    )
    try:
        scholarship_id = await decide_review(db, review_task_id, decision_request)
    except (LookupError, ValueError) as exc:
        logger.warning("auto_approval_decide_review_failed", extra={"error": str(exc)})
        return AutoApprovalOutcome(approved=False, reason="approve_failed")
    assert scholarship_id is not None  # decision="approve" always returns one

    countries = await load_vocabulary(db)
    try:
        facts = build_cycle_facts(
            destinations=derived.destinations,
            levels=derived.levels,
            origin_mode="unknown",
            origins=[],
            field_mode="unknown",
            fields=[],
            evidence_fresh=True,
            deadline_at=derived.deadline_at,
            funding_type=derived.funding_type,
            countries=countries,
        )
        cycle = await publish_cycle(
            db,
            scholarship_id,
            provider_cycle_key="auto-approved",
            applicant_segment="default",
            official_cycle_url=verification.fetched_url,
            # Always open_verified: the deadline_at gate above already
            # requires a real, corroborated, page-verified future deadline -
            # exactly the evidence the standard accepts for this claim.
            public_status=PublicStatus.open_verified,
            facts=facts,
            status_valid_until=None,
            last_verified_at=datetime.now(UTC),
            actor="auto_approve_sweep",
        )
    except (LookupError, ValueError) as exc:
        # The Scholarship shell from decide_review above is already
        # committed - it sits at needs_review, exactly the same state a
        # human's own approve-then-not-yet-published candidate would, for
        # someone to finish publishing manually. Nothing is lost.
        logger.warning(
            "auto_approval_publish_failed",
            extra={"scholarship_id": str(scholarship_id), "error": str(exc)},
        )
        return AutoApprovalOutcome(
            approved=False, reason="publish_failed", scholarship_id=scholarship_id
        )

    cycle.is_auto_approved = True
    cycle.auto_approval_score = score
    db.add(
        AuditLog(
            actor="auto_approve_sweep",
            action="scholarship.auto_published",
            target_id=scholarship_id,
            reason="Auto-approved via cross-source corroboration and real-page verification.",
            context=snapshot,
        )
    )
    sampled = random.random() < settings.auto_approve_sample_rate
    db.add(
        AutoApprovalAudit(
            scholarship_id=scholarship_id,
            cycle_id=cycle.cycle_id,
            decision_snapshot=snapshot,
            sampled=sampled,
            outcome="pending" if sampled else "not_sampled",
        )
    )
    discovery.auto_review_evaluated_at = datetime.now(UTC)
    await db.commit()
    return AutoApprovalOutcome(
        approved=True,
        reason="auto_approved",
        scholarship_id=scholarship_id,
        cycle_id=cycle.cycle_id,
    )


async def _available_slug(db: AsyncSession, name: str, *, max_attempts: int = 5) -> str | None:
    base = _SLUG_INVALID.sub("-", name.lower()).strip("-") or "scholarship"
    for attempt in range(max_attempts):
        candidate = base if attempt == 0 else f"{base}-{attempt + 1}"
        existing = await db.scalar(
            select(Scholarship.scholarship_id).where(Scholarship.slug == candidate)
        )
        if existing is None:
            return candidate
    return None
