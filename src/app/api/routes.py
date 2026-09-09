import asyncio
import hmac
import logging
import uuid
from datetime import UTC, datetime
from time import perf_counter
from typing import Literal, cast

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.detail_schemas import MatchProfileRequest, ScholarshipDetailResponse
from app.api.ingestion_schemas import FeedImportRequest, FeedImportResponse
from app.api.job_schemas import JobRequest, JobResponse
from app.api.join_schemas import JoinIntentRequest, JoinIntentResponse
from app.api.provider_schemas import ProviderCreateRequest, ProviderListResponse, ProviderRead
from app.api.review_schemas import (
    BulkReviewDecisionRequest,
    BulkReviewDecisionResponse,
    BulkReviewDecisionResult,
    PublishCycleRequest,
    PublishCycleResponse,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    ReviewQueueResponse,
    ReviewTaskSummary,
    RunDueJobsResponse,
    WithdrawRequest,
    WithdrawResponse,
)
from app.api.schemas import (
    ReplaySearchMeta,
    SearchMeta,
    SearchReplayResponse,
    SearchRequest,
    SearchResponse,
    SearchResult,
    TaxonomiesResponse,
    TaxonomyItem,
)
from app.api.scholarship_admin_schemas import (
    ScholarshipAdminListResponse,
    ScholarshipAdminRead,
    ScholarshipCycleAdminRead,
)
from app.api.source_schemas import SourceCreateRequest, SourceListResponse, SourceRead
from app.core.config import Settings, get_settings
from app.core.cursors import decode_cursor, encode_cursor
from app.core.ids import new_uuid7
from app.core.rate_limit import InMemoryRateLimiter
from app.domain.facts import derive_facts as _derive_facts
from app.domain.jobs import JobState
from app.domain.matching import MatchDecision, SearchProfile, evaluate_match
from app.domain.models import (
    Discovery,
    JoinRequest,
    Provider,
    PublicStatus,
    RecordState,
    ReviewTask,
    Scholarship,
    ScholarshipCycle,
    Search,
    Source,
    SourcePage,
)
from app.domain.publication import build_cycle_facts
from app.domain.return_urls import is_allowed_return_url
from app.domain.snapshots import build_result_snapshot
from app.domain.status import evaluate_public_status, evaluate_status_detail
from app.domain.taxonomy import TAXONOMY, normalize_search_filters
from app.infra.core_client import CoreJoinClient
from app.infra.countries import load_vocabulary
from app.infra.db import get_db
from app.infra.ingestion import import_feed_records
from app.infra.jobs import count_due_jobs, due_jobs, enqueue_job
from app.infra.match_explanations import get_match_explanation
from app.infra.outbox import enqueue_analytics_event
from app.infra.providers import create_provider, list_providers
from app.infra.publication import publish_cycle
from app.infra.qstash import ALLOWED_JOB_KINDS, QStashVerificationConfig, QStashVerifier
from app.infra.reviews import decide_review
from app.infra.scholarship_admin import search_scholarships
from app.infra.sessions import (
    SESSION_COOKIE,
    filter_digest,
    get_existing_session,
    get_or_create_session,
    record_search_response,
)
from app.infra.sources import create_source, deactivate_source, list_sources
from app.infra.withdrawals import withdraw_scholarship
from app.infra.worker import execute_job

logger = logging.getLogger("app.api")
router = APIRouter()
search_limiter = InMemoryRateLimiter()
# The join path is far more expensive than a search: it calls Core.
JOIN_INTENTS_PER_MINUTE = 5
# Eligibility is evaluated in Python, so one search scans the published set.
# Comfortably above the 150-record launch target and the 300-record maturity
# target; passing it emits a warning instead of silently truncating results.
PUBLISHED_CYCLE_SCAN_LIMIT = 2000
#: Version of the deterministic ranking policy recorded with every response.
#: Bump this whenever evaluate_match's actual gating/scoring semantics
#: change (not just the vocabulary it validates against) - v2 marks the
#: ISCED-F field-matching rewrite (equality -> broad/narrow set
#: intersection, commit 68157fd) that shipped without a version bump.
MATCH_POLICY_VERSION = "match-v2"
join_limiter = InMemoryRateLimiter()


async def require_internal_service(x_service_token: str | None = Header(default=None)) -> None:
    from app.core.config import get_settings

    expected = get_settings().internal_service_token
    # Constant time: a short-circuiting compare leaks the token byte by byte to
    # anyone close enough to measure, and the platform proxy is that close.
    if not expected or not hmac.compare_digest(x_service_token or "", expected):
        raise HTTPException(status_code=401, detail="Internal service authentication required")


@router.post(
    "/internal/import/feed",
    response_model=FeedImportResponse,
    dependencies=[Depends(require_internal_service)],
)
async def import_feed(
    payload: FeedImportRequest, db: AsyncSession = Depends(get_db)
) -> FeedImportResponse:
    outcome = await import_feed_records(db, payload.records)
    return FeedImportResponse(
        crawl_run_id=outcome.crawl_run_id,
        imported=outcome.imported,
        repeated=outcome.repeated,
        changed=outcome.changed,
        rejected=outcome.rejected,
    )


def _source_read(source: Source) -> SourceRead:
    return SourceRead(
        source_id=source.source_id,
        name=source.name,
        source_type=source.source_type,
        authority_grade=source.authority_grade,
        approved_domains=source.approved_domains,
        active=source.active,
    )


@router.post(
    "/internal/admin/sources",
    response_model=SourceRead,
    status_code=201,
    dependencies=[Depends(require_internal_service)],
)
async def create_source_route(
    payload: SourceCreateRequest, db: AsyncSession = Depends(get_db)
) -> SourceRead:
    source = await create_source(db, payload)
    return _source_read(source)


@router.get(
    "/internal/admin/sources",
    response_model=SourceListResponse,
    dependencies=[Depends(require_internal_service)],
)
async def list_sources_route(db: AsyncSession = Depends(get_db)) -> SourceListResponse:
    sources = await list_sources(db)
    return SourceListResponse(data=[_source_read(source) for source in sources])


@router.post(
    "/internal/admin/sources/{source_id}/deactivate",
    response_model=SourceRead,
    dependencies=[Depends(require_internal_service)],
)
async def deactivate_source_route(
    source_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> SourceRead:
    """Stop a source - test data, a retired feed - from being crawled again."""
    try:
        source = await deactivate_source(db, source_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _source_read(source)


def _provider_read(provider: Provider) -> ProviderRead:
    return ProviderRead(
        provider_id=provider.provider_id,
        name=provider.name,
        approved_domains=provider.approved_domains,
        country=provider.country,
    )


@router.post(
    "/internal/admin/providers",
    response_model=ProviderRead,
    status_code=201,
    dependencies=[Depends(require_internal_service)],
)
async def create_provider_route(
    payload: ProviderCreateRequest, db: AsyncSession = Depends(get_db)
) -> ProviderRead:
    countries = await load_vocabulary(db) if payload.country is not None else None
    try:
        provider = await create_provider(db, payload, countries=countries)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _provider_read(provider)


@router.get(
    "/internal/admin/providers",
    response_model=ProviderListResponse,
    dependencies=[Depends(require_internal_service)],
)
async def list_providers_route(db: AsyncSession = Depends(get_db)) -> ProviderListResponse:
    providers = await list_providers(db)
    return ProviderListResponse(data=[_provider_read(provider) for provider in providers])


def _cycle_admin_read(cycle: ScholarshipCycle, evaluated_at: datetime) -> ScholarshipCycleAdminRead:
    # facts isn't schema-enforced below publish() and can come back as
    # Python None even though the column is NOT NULL - JSONB.none_as_null
    # defaults to False, so an ORM-level `cycle.facts = None` persists as
    # the JSON null literal, not SQL NULL.
    facts = cycle.facts or {}
    # Route the deadline fields through the same sanitizer _search_result/
    # _detail use, rather than reading facts.get(...) directly here too - an
    # out-of-contract deadline_timezone (not a string) used to reach
    # ZoneInfo(...) unguarded and raise TypeError, 500-ing this whole
    # listing over one bad cycle. The `facts=` field below still returns
    # the raw dict, unlike the public detail endpoint - this is an admin
    # debugging view, where seeing the actual corruption is the point.
    derived = _derive_facts(facts)
    return ScholarshipCycleAdminRead(
        cycle_id=cycle.cycle_id,
        provider_cycle_key=cycle.provider_cycle_key,
        applicant_segment=cycle.applicant_segment,
        official_cycle_url=cycle.official_cycle_url,
        public_status=cycle.public_status.value,
        evaluated_public_status=evaluate_public_status(
            cycle.public_status,
            deadline_at=derived.deadline_at,
            deadline_precision=derived.deadline_precision,
            deadline_timezone=derived.deadline_timezone,
            status_valid_until=cycle.status_valid_until,
            now=evaluated_at,
        ).value,
        status_valid_until=cycle.status_valid_until,
        last_verified_at=cycle.last_verified_at,
        facts=facts,
    )


def _scholarship_admin_read(
    scholarship: Scholarship, evaluated_at: datetime
) -> ScholarshipAdminRead:
    return ScholarshipAdminRead(
        scholarship_id=scholarship.scholarship_id,
        slug=scholarship.slug,
        name=scholarship.name,
        official_home_url=scholarship.official_home_url,
        award_type=scholarship.award_type,
        lifecycle_state=scholarship.lifecycle_state.value,
        provider_id=scholarship.provider_id,
        provider_name=scholarship.provider.name if scholarship.provider else "",
        cycles=[_cycle_admin_read(cycle, evaluated_at) for cycle in scholarship.cycles],
    )


@router.get(
    "/internal/admin/scholarships",
    response_model=ScholarshipAdminListResponse,
    dependencies=[Depends(require_internal_service)],
)
async def list_scholarships_route(
    q: str | None = Query(default=None, min_length=1, max_length=255),
    lifecycle_state: RecordState | None = None,
    provider_id: uuid.UUID | None = None,
    public_status: PublicStatus | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> ScholarshipAdminListResponse:
    """Search and filter every scholarship regardless of lifecycle state.

    For reviewers and testers confirming what an import or publish actually
    produced - not the public `/search` route, which only matches published,
    destination/level/field-eligible cycles for an applicant. `public_status`
    filters on the value each cycle has stored; each returned cycle also
    carries `evaluated_public_status`, recomputed the way search and detail
    do, so a stale stored `open_verified` past its deadline is visible as
    such rather than hidden behind the value last written.
    """
    evaluated_at = datetime.now(UTC)
    rows, total = await search_scholarships(
        db,
        q=q,
        lifecycle_state=lifecycle_state,
        provider_id=provider_id,
        public_status=public_status,
        limit=limit,
        offset=offset,
    )
    return ScholarshipAdminListResponse(
        data=[_scholarship_admin_read(row, evaluated_at) for row in rows], total=total
    )


def _qstash_destination(request: Request, kind: str | None = None) -> str:
    """Return the URL QStash signed as `sub`.

    `request.url` only reconstructs that URL when the app is reached directly;
    a platform proxy leaves the scheme and host rewritten, so the configured
    public callback URL wins whenever it is set.
    """
    configured = get_settings().qstash_expected_destination
    if not configured:
        # Fail closed. `request.url` is rebuilt from the Host header and
        # X-Forwarded-Proto, both attacker-supplied once the platform proxy is
        # trusted, which would reduce the `sub` binding to a path comparison
        # and let a signature issued for one environment replay against another.
        return ""
    if kind is None:
        return configured
    return f"{configured.rstrip('/')}/{kind}"


async def _verified_job_body(request: Request, destination: str) -> bytes:
    """Return the raw body only once a QStash signature covers it."""
    raw_body = await request.body()
    settings = get_settings()
    verifier = QStashVerifier(
        QStashVerificationConfig(
            settings.qstash_current_signing_key,
            settings.qstash_next_signing_key,
            destination,
        )
    )
    result = verifier.verify(raw_body=raw_body, signature=request.headers.get("Upstash-Signature"))
    if not result.ok:
        # The client only ever sees a generic 401; the reason goes to the
        # operator log so a misconfigured destination or key is diagnosable
        # without probing the endpoint. Destinations are public URLs, not
        # secrets, so logging the mismatch is safe.
        logger.warning(
            "qstash_signature_rejected",
            extra={
                "request_id": getattr(request.state, "request_id", ""),
                "reason": result.reason,
                "expected_destination": destination,
                "signed_destination": result.signed_destination or "",
            },
        )
        raise HTTPException(status_code=401, detail="Invalid QStash signature")
    return raw_body


def _parse_job(raw_body: bytes) -> JobRequest:
    try:
        return JobRequest.model_validate_json(raw_body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid job payload") from exc


#: Kinds a QStash *schedule* delivers on a recurring cadence with one static
#: stored body. `ProcessingJob.dedupe_key` is permanently unique, so reusing
#: whatever key that static body carries would let only the first-ever
#: delivery actually run - every later delivery would just report that first
#: job's now-stale result forever (see README's "replayed delivery... reports
#: that job's current state without re-running it"). Recomputing a
#: week-scoped key here, ignoring the delivered payload's own dedupe_key,
#: keeps same-week retries idempotent while letting next week run for real.
RECURRING_WEEKLY_KINDS = frozenset({"harvest_parsebot"})
#: Same static-body-recurring-schedule pattern as RECURRING_WEEKLY_KINDS,
#: just finer-grained: the data-verification standard calls for a sweep at
#: least every 15 minutes, so a QStash *schedule* redelivers a static body
#: on that cadence and this recomputes a fresh dedupe key each quarter-hour
#: rather than deduping every delivery after the first-ever one forever.
RECURRING_QUARTER_HOUR_KINDS = frozenset({"refresh_status", "reverify_due"})


def _weekly_dedupe_key(kind: str) -> str:
    iso_year, iso_week, _ = datetime.now(UTC).isocalendar()
    return f"{kind}:{iso_year}-W{iso_week:02d}"


def _quarter_hour_dedupe_key(kind: str) -> str:
    now = datetime.now(UTC)
    bucket = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    return f"{kind}:{bucket.isoformat()}"


async def _enqueue(kind: str, job_request: JobRequest, db: AsyncSession) -> JobResponse:
    """Enqueue a job, then run it before acknowledging the delivery.

    Acknowledge success only after durable completion: enqueuing and returning
    200 without running anything left every QStash-delivered job sitting at
    `queued` forever, since nothing else in the deployed app ever called
    execute_job.

    Eligibility is judged from the job's stored state, not from whether this
    particular delivery created the row: a job enqueued before this fix
    existed, or by a request that crashed after enqueueing but before
    executing, is still sitting at `queued` and must still run on the next
    delivery - keying this off `created` instead would silently reproduce the
    exact bug this fixes for anything already stuck. A job already completed,
    still running, or not yet due for retry is reported as-is without a second
    attempt; claim_job's own state machine is the source of truth for that,
    checked here first so execute_job is only called when it would actually
    proceed.
    """
    if kind not in ALLOWED_JOB_KINDS:
        raise HTTPException(status_code=404, detail="Unknown job kind")
    dedupe_key = (
        _weekly_dedupe_key(kind)
        if kind in RECURRING_WEEKLY_KINDS
        else _quarter_hour_dedupe_key(kind)
        if kind in RECURRING_QUARTER_HOUR_KINDS
        else job_request.dedupe_key
    )
    job, created = await enqueue_job(db, kind, dedupe_key, job_request.payload)
    now = datetime.now(UTC)
    eligible = job.state in (JobState.queued.value, JobState.retry_wait.value) and (
        job.next_attempt_at is None or job.next_attempt_at <= now
    )
    if not eligible:
        return JobResponse(job_id=job.job_id, state=job.state, created=created)
    try:
        state = await execute_job(db, job.job_id)
    except Exception as exc:
        await db.refresh(job)
        # execute_job already recorded the failure durably (retry_wait or
        # failed_review) before re-raising. A retryable non-2xx lets QStash's
        # own retry schedule take over rather than reporting the enqueue as
        # successful while the work behind it failed.
        raise HTTPException(
            status_code=502, detail=f"Job execution failed: {job.last_error or exc}"
        ) from exc
    return JobResponse(job_id=job.job_id, state=state, created=created)


@router.post("/internal/jobs", response_model=JobResponse)
async def receive_fixed_job(request: Request, db: AsyncSession = Depends(get_db)) -> JobResponse:
    """Receive every QStash job at one stable, signature-bound destination."""
    raw_body = await _verified_job_body(request, _qstash_destination(request))
    job_request = _parse_job(raw_body)
    if not job_request.kind:
        raise HTTPException(status_code=422, detail="Job kind is required")
    return await _enqueue(job_request.kind, job_request, db)


@router.post("/internal/jobs/{kind}", response_model=JobResponse)
async def receive_job(
    kind: str, request: Request, db: AsyncSession = Depends(get_db)
) -> JobResponse:
    """Compatibility route; new QStash destinations should use `/internal/jobs`."""
    raw_body = await _verified_job_body(request, _qstash_destination(request, kind))
    return await _enqueue(kind, _parse_job(raw_body), db)


@router.post(
    "/internal/admin/reviews/{review_task_id}/decision",
    response_model=ReviewDecisionResponse,
    dependencies=[Depends(require_internal_service)],
)
async def review_decision(
    review_task_id: uuid.UUID, payload: ReviewDecisionRequest, db: AsyncSession = Depends(get_db)
) -> ReviewDecisionResponse:
    try:
        scholarship_id = await decide_review(db, review_task_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ReviewDecisionResponse(
        review_task_id=review_task_id, decision=payload.decision, scholarship_id=scholarship_id
    )


@router.post(
    "/internal/admin/reviews/bulk-decision",
    response_model=BulkReviewDecisionResponse,
    dependencies=[Depends(require_internal_service)],
)
async def bulk_review_decision(
    payload: BulkReviewDecisionRequest, db: AsyncSession = Depends(get_db)
) -> BulkReviewDecisionResponse:
    """Apply up to 10 review decisions in one call.

    Each item commits on its own inside decide_review; one bad item - an
    already-resolved task, an invalid award type, a duplicate slug - is
    rolled back and reported for that item alone, never failing the other
    nine. That is the whole point of a bulk endpoint: a reviewer working
    through a batch should not lose 9 good decisions because 1 was malformed.
    """
    results: list[BulkReviewDecisionResult] = []
    for item in payload.decisions:
        try:
            scholarship_id = await decide_review(db, item.review_task_id, item)
            results.append(
                BulkReviewDecisionResult(
                    review_task_id=item.review_task_id,
                    success=True,
                    decision=item.decision,
                    scholarship_id=scholarship_id,
                )
            )
        except Exception as exc:  # isolate one item's failure from the rest of the batch
            await db.rollback()
            results.append(
                BulkReviewDecisionResult(
                    review_task_id=item.review_task_id,
                    success=False,
                    decision=item.decision,
                    error=str(exc),
                )
            )
    return BulkReviewDecisionResponse(results=results)


def _search_result(
    row: ScholarshipCycle, decision: MatchDecision, evaluated_at: datetime
) -> SearchResult | None:
    """Build one public result, re-deriving status at read time.

    A stored `open_verified` whose deadline or freshness boundary has passed
    must not be returned as open just because no sweep has run yet; search
    previously returned the stored value untouched while the detail endpoint
    re-evaluated it, so the two disagreed and search could claim a closed
    award was open.
    """
    facts = row.facts or {}
    derived = _derive_facts(facts)
    status = evaluate_public_status(
        row.public_status,
        deadline_at=derived.deadline_at,
        deadline_precision=derived.deadline_precision,
        deadline_timezone=derived.deadline_timezone,
        status_valid_until=row.status_valid_until,
        now=evaluated_at,
    )
    status_detail = evaluate_status_detail(
        status,
        deadline_at=derived.deadline_at,
        deadline_precision=derived.deadline_precision,
        deadline_timezone=derived.deadline_timezone,
        expected_reopen_month=derived.expected_reopen_month,
        now=evaluated_at,
    )
    if status == PublicStatus.status_unknown:
        return None
    caveats = list(decision.caveats)
    if status != row.public_status:
        caveats.append("Current status evidence requires re-verification.")
    return SearchResult(
        scholarship_id=row.scholarship_id,
        cycle_id=row.cycle_id,
        name=row.scholarship.name,
        provider=row.scholarship.provider.name,
        award_type=row.scholarship.award_type,
        status=status_detail,
        status_detail=status_detail,
        fit=cast(Literal["confirmed", "possible"], decision.fit),
        eligibility_note=derived.eligibility_note,
        field_names=derived.field_names,
        fields=derived.fields,
        programme_names=derived.programme_names,
        destinations=derived.destinations,
        deadline_at=derived.deadline_at,
        deadline_precision=derived.public_deadline_precision,
        degree_levels=derived.degree_levels,
        expected_reopen_month=derived.expected_reopen_month,
        funding_type=derived.funding_type,
        provider_country=row.scholarship.provider.country,
        official_url=row.official_cycle_url,
        last_verified_at=row.last_verified_at,
        caveats=caveats,
    )


def _result_sort_value(item: SearchResult, evaluated_at: datetime) -> tuple[int, str]:
    """Return the secondary ordering value for the public status bucket."""
    if item.status in {"open", "closing_soon"}:
        deadline = item.deadline_at.isoformat() if item.deadline_at else ""
        return (0 if item.deadline_at is not None else 1, deadline)
    month = item.expected_reopen_month
    if month is None:
        return (1, "13")
    distance = (month - evaluated_at.month) % 12
    return (0, f"{distance:02d}")


@router.get(
    "/internal/admin/reviews",
    response_model=ReviewQueueResponse,
    dependencies=[Depends(require_internal_service)],
)
async def review_queue(
    state: Literal["open", "resolved"] = "open",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> ReviewQueueResponse:
    """The reviewer's work list, highest priority and oldest first.

    Carries the discovery's excerpt and source URL, not just its title: a
    reviewer cannot verify anything - or even tell two similarly-titled
    candidates apart - from a bare title alone.
    """
    rows = list(
        await db.execute(
            select(
                ReviewTask,
                Discovery.raw_title,
                Discovery.raw_excerpt,
                Discovery.extracted_facts,
                SourcePage.normalized_url,
            )
            .outerjoin(Discovery, Discovery.discovery_id == ReviewTask.discovery_id)
            .outerjoin(SourcePage, SourcePage.page_id == Discovery.source_page_id)
            .where(ReviewTask.state == state)
            .order_by(ReviewTask.priority, ReviewTask.created_at)
            .offset(offset)
            .limit(limit)
        )
    )
    open_count = await db.scalar(
        select(func.count()).select_from(ReviewTask).where(ReviewTask.state == "open")
    )
    return ReviewQueueResponse(
        data=[
            ReviewTaskSummary(
                review_task_id=task.review_task_id,
                reason=task.reason,
                priority=task.priority,
                state=task.state,
                discovery_id=task.discovery_id,
                revision_id=task.revision_id,
                cycle_id=task.cycle_id,
                raw_title=raw_title,
                raw_excerpt=raw_excerpt,
                extracted_facts=extracted_facts,
                draft_recommendation=task.draft_recommendation,
                source_url=source_url,
                created_at=task.created_at,
            )
            for task, raw_title, raw_excerpt, extracted_facts, source_url in rows
        ],
        open_count=int(open_count or 0),
    )


@router.post(
    "/internal/admin/scholarships/{scholarship_id}/withdraw",
    response_model=WithdrawResponse,
    dependencies=[Depends(require_internal_service)],
)
async def withdraw(
    scholarship_id: uuid.UUID,
    payload: WithdrawRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WithdrawResponse:
    """Remove a misleading published record from public results immediately."""
    try:
        cycles = await withdraw_scholarship(
            db, scholarship_id, reason=payload.reason, actor="internal_service"
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    logger.warning(
        "scholarship_withdrawn",
        extra={"request_id": getattr(request.state, "request_id", "")},
    )
    return WithdrawResponse(
        scholarship_id=scholarship_id,
        lifecycle_state=RecordState.withdrawn.value,
        withdrawn_cycles=cycles,
    )


@router.post(
    "/internal/admin/scholarships/{scholarship_id}/publish",
    response_model=PublishCycleResponse,
    dependencies=[Depends(require_internal_service)],
)
async def publish(
    scholarship_id: uuid.UUID,
    payload: PublishCycleRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> PublishCycleResponse:
    """Publish one application cycle, making an approved record public.

    Vocabulary validation (unknown country/degree/field, an empty restricted
    list) is a 422: the request itself is malformed. A conflict with the
    record's current state (already withdrawn, a duplicate cycle key) is a
    409: the request is well-formed but cannot apply right now.
    """
    countries = await load_vocabulary(db)
    try:
        facts = build_cycle_facts(
            destinations=payload.destinations,
            levels=payload.levels,
            origin_mode=payload.origin_mode,
            origins=payload.origins,
            field_mode=payload.field_mode,
            fields=payload.fields,
            evidence_fresh=payload.evidence_fresh,
            deadline_at=payload.deadline_at,
            deadline_precision=payload.deadline_precision,
            deadline_timezone=payload.deadline_timezone,
            eligibility_note=payload.eligibility_note,
            expected_reopen_month=payload.expected_reopen_month,
            field_names=payload.field_names,
            programme_names=payload.programme_names,
            funding_type=payload.funding_type,
            countries=countries,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        cycle = await publish_cycle(
            db,
            scholarship_id,
            provider_cycle_key=payload.provider_cycle_key,
            applicant_segment=payload.applicant_segment,
            official_cycle_url=str(payload.official_cycle_url),
            public_status=PublicStatus(payload.public_status),
            facts=facts,
            status_valid_until=payload.status_valid_until,
            last_verified_at=payload.last_verified_at,
            actor="internal_service",
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    logger.warning(
        "scholarship_published",
        extra={"request_id": getattr(request.state, "request_id", "")},
    )
    return PublishCycleResponse(
        scholarship_id=scholarship_id,
        cycle_id=cycle.cycle_id,
        lifecycle_state=RecordState.published.value,
        public_status=cycle.public_status.value,
    )


@router.post(
    "/internal/admin/jobs/run-due",
    response_model=RunDueJobsResponse,
    dependencies=[Depends(require_internal_service)],
)
async def run_due_jobs_route(
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> RunDueJobsResponse:
    """Manually execute every job currently due, one call at a time.

    A job created as a side effect of another request - feed import's
    normalize_discovery/link_canonical jobs, most concretely - is never
    delivered to QStash, so nothing else in this service executes it; only a
    real QStash delivery to /internal/jobs runs a job. This is the stopgap for
    that gap until jobs are published to QStash on creation, and it doubles as
    manual recovery once the recurring schedule that would otherwise call this
    automatically exists. Safe to call repeatedly: a job already completed, or
    not yet due for retry, is simply not selected again.
    """
    jobs = await due_jobs(db, limit=limit)
    completed = failed = 0
    for job in jobs:
        try:
            await execute_job(db, job.job_id)
            completed += 1
        except Exception:
            failed += 1
    remaining = await count_due_jobs(db)
    return RunDueJobsResponse(completed=completed, failed=failed, remaining=remaining)


def _detail(row: ScholarshipCycle) -> ScholarshipDetailResponse:
    facts = row.facts or {}
    derived = _derive_facts(facts)
    evaluated_at = datetime.now(UTC)
    status = evaluate_public_status(
        row.public_status,
        deadline_at=derived.deadline_at,
        deadline_precision=derived.deadline_precision,
        deadline_timezone=derived.deadline_timezone,
        status_valid_until=row.status_valid_until,
        now=evaluated_at,
    )
    status_detail = evaluate_status_detail(
        status,
        deadline_at=derived.deadline_at,
        deadline_precision=derived.deadline_precision,
        deadline_timezone=derived.deadline_timezone,
        expected_reopen_month=derived.expected_reopen_month,
        now=evaluated_at,
    )
    caveats: list[str] = []
    if status != row.public_status:
        caveats.append("Current status evidence requires re-verification.")
    return ScholarshipDetailResponse(
        scholarship_id=row.scholarship_id,
        cycle_id=row.cycle_id,
        name=row.scholarship.name,
        provider=row.scholarship.provider.name,
        award_type=row.scholarship.award_type,
        status=status.value,
        status_detail=status_detail,
        status_valid_until=row.status_valid_until,
        official_url=row.official_cycle_url,
        facts=derived.sanitized_dict,
        last_verified_at=row.last_verified_at,
        eligibility_note=derived.eligibility_note,
        field_names=derived.field_names,
        fields=derived.fields,
        programme_names=derived.programme_names,
        destinations=derived.destinations,
        deadline_at=derived.deadline_at,
        deadline_precision=derived.public_deadline_precision,
        degree_levels=derived.degree_levels,
        expected_reopen_month=derived.expected_reopen_month,
        funding_type=derived.funding_type,
        provider_country=row.scholarship.provider.country,
        caveats=caveats,
    )


def _taxonomy_items(mapping: dict[str, str], key: str, wanted: set[str]) -> list[TaxonomyItem]:
    if key not in wanted:
        return []
    return [TaxonomyItem(code=code, label=label) for code, label in mapping.items()]


TAXONOMY_TYPES = frozenset(
    {
        "countries",
        "destinations",
        "degrees",
        "fields",
        "award_types",
        "funding_types",
    }
)


@router.get("/taxonomies", response_model=TaxonomiesResponse)
async def taxonomies(
    request: Request,
    types: list[str] | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> TaxonomiesResponse:
    """The vocabularies a search form is built from.

    Countries come from the mirror of Core's catalogue; destinations are the
    subset with verified coverage, returned separately so the form can offer
    every origin while limiting where a search can be run.

    `types` narrows the response to just the requested collections (e.g.
    `?types=fields`) - omit it, or send it empty
    (`?types=`), for the full vocabulary. Unrequested collections come back
    as empty lists, not omitted keys, so the response shape never changes.

    Some HTTP clients serialize a repeated param with a bracket suffix
    (`types[]=fields`) instead of FastAPI's plain repeated-key form; that key
    doesn't bind to the `types` parameter above, so accept it explicitly too
    rather than silently ignoring it and falling back to the full,
    unfiltered vocabulary.
    """
    bracketed = request.query_params.getlist("types[]")
    wanted = {value for value in (*(types or []), *bracketed) if value}
    if not wanted:
        wanted = set(TAXONOMY_TYPES)
    unknown = wanted - TAXONOMY_TYPES
    if unknown:
        raise HTTPException(
            status_code=422, detail=f"Unknown taxonomy type(s): {', '.join(sorted(unknown))}"
        )

    country_names: dict[str, str] = {}
    destination_codes: frozenset[str] = frozenset()
    if wanted & {"countries", "destinations"}:
        vocabulary = await load_vocabulary(db)
        country_names = vocabulary.names
        destination_codes = vocabulary.destinations

    return TaxonomiesResponse(
        version=TAXONOMY.version,
        countries=[
            TaxonomyItem(code=code, label=label) for code, label in sorted(country_names.items())
        ]
        if "countries" in wanted
        else [],
        destinations=[
            TaxonomyItem(code=code, label=country_names[code])
            for code in sorted(destination_codes)
            if code in country_names
        ]
        if "destinations" in wanted
        else [],
        degrees=_taxonomy_items(TAXONOMY.degrees, "degrees", wanted),
        fields=_taxonomy_items(TAXONOMY.fields, "fields", wanted),
        award_types=_taxonomy_items(TAXONOMY.award_types, "award_types", wanted),
        funding_types=_taxonomy_items(TAXONOMY.funding_types, "funding_types", wanted),
    )


@router.post("/join-intents", response_model=JoinIntentResponse)
async def create_join_intent(
    payload: JoinIntentRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> JoinIntentResponse:
    """Create a consented, idempotent handoff from Finder to the Core product."""
    if not payload.consent:
        raise HTTPException(status_code=422, detail="Consent is required")
    settings = get_settings()
    session = await get_or_create_session(db, response, request.cookies.get(SESSION_COOKIE))
    if not join_limiter.allow(str(session.session_id), JOIN_INTENTS_PER_MINUTE):
        raise HTTPException(
            status_code=429,
            detail="Join request rate limit exceeded",
            headers={"Retry-After": "60"},
        )
    if not all(
        (
            settings.core_join_intent_url,
            settings.core_service_token,
            settings.core_allowed_return_url_prefix,
        )
    ):
        raise HTTPException(
            status_code=503, detail="Core join-intent integration is not configured"
        )
    return_url = str(payload.return_url)
    if not is_allowed_return_url(return_url, settings.core_allowed_return_url_prefix or ""):
        raise HTTPException(status_code=422, detail="Return URL is not allowed")
    # A search may only be handed to Core by the session that ran it. Without
    # this the search id alone was enough for anyone to transfer another
    # visitor's filters and receive their continue URL and handoff token.
    search = await db.scalar(
        select(Search).where(
            Search.search_id == payload.search_id,
            Search.session_id == session.session_id,
        )
    )
    if search is None:
        raise HTTPException(status_code=404, detail="Search not found")
    existing = await db.scalar(
        select(JoinRequest).where(JoinRequest.idempotency_key == payload.idempotency_key)
    )
    if existing is None:
        existing = JoinRequest(idempotency_key=payload.idempotency_key)
        db.add(existing)
        await db.flush()
    core_payload = {
        "source_product": "scholarship_finder",
        "source_session_id": str(search.session_id) if search.session_id else None,
        "context_version": "v1",
        "profile_context": search.filters,
        "product_context": {"search_id": str(search.search_id)},
        "consent": {"notice": "finder_join_intent_v1", "action": "accepted"},
        "return_url": return_url,
    }
    try:
        result = await CoreJoinClient(
            settings.core_join_intent_url or "", settings.core_service_token or ""
        ).create_join_intent(core_payload, payload.idempotency_key)
    except (httpx.HTTPError, ValueError) as exc:
        existing.outcome = "failed"
        raise HTTPException(status_code=503, detail="Core join-intent service unavailable") from exc
    existing.core_join_intent_id = str(result.get("id")) if result.get("id") else None
    existing.outcome = str(result.get("status", "created"))
    return JoinIntentResponse.model_validate(
        {
            "status": existing.outcome,
            "continue_url": result.get("continue_url"),
            "handoff_token": result.get("handoff_token"),
        }
    )


search_replay_limiter = InMemoryRateLimiter()


@router.get("/search/{search_id}", response_model=SearchReplayResponse)
async def get_search(
    search_id: uuid.UUID, request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> SearchReplayResponse:
    """Replay a retained search's first page without re-running matching.

    Scoped to the requesting session, the same as `create_join_intent`'s own
    `search_id`/`session_id` check: a search id alone must not be enough for
    a different visitor to read someone else's filters/results. A
    syntactically valid but unknown, someone else's, or expired search id all
    collapse to the same 404 - nothing here should let a caller distinguish
    "never existed" from "not yours" (a malformed, non-UUID id is a separate,
    ordinary 422 from FastAPI's own path-parameter parsing, same as every
    other UUID path parameter in this API).

    A scholarship withdrawn since the original search is filtered out of the
    replayed `data` rather than shown as a still-valid match: the whole point
    of withdrawal is that the record is actively misleading, and this replay
    otherwise has no other opportunity to reflect that within its 30-day
    retention window. `meta.total_match_count`/`warnings` stay as originally
    recorded - an accurate history of what the search itself found - only
    the displayed rows are filtered.
    """
    settings = get_settings()
    # A private, session-scoped response - unlike this API's other GETs,
    # which all serve public, unscoped data safe for a shared cache.
    response.headers["Cache-Control"] = "private, no-store"
    limiter_key = request.client.host if request.client else "unknown"
    if not search_replay_limiter.allow(limiter_key, settings.api_rate_limit_per_minute):
        raise HTTPException(
            status_code=429,
            detail="Search replay rate limit exceeded",
            headers={"Retry-After": "60"},
        )
    session = await get_existing_session(db, request.cookies.get(SESSION_COOKIE))
    if session is None:
        raise HTTPException(status_code=404, detail="Search not found")
    stored = await db.scalar(
        select(Search).where(
            Search.search_id == search_id,
            Search.session_id == session.session_id,
            Search.page_number == 1,
            Search.expires_at > datetime.now(UTC),
        )
    )
    if stored is None:
        raise HTTPException(status_code=404, detail="Search not found")
    try:
        return await _replay_search(db, stored, settings)
    except (KeyError, TypeError, ValidationError) as exc:
        # result_snapshot is only ever written by build_result_snapshot, so
        # this should never actually be reachable - but nothing enforces
        # that at the database level (it's a bare JSONB column, defaulting
        # to `{}`), and a stored row shaped for an older/narrower
        # ALLOWED_RESULT_KEYS is exactly the kind of "trusted but not
        # guaranteed" data this repo's own facts-contract work already
        # treats as reachable. A row this endpoint can't safely replay is
        # unusable the same way a missing one is - not a 500.
        logger.warning(
            "search_replay_snapshot_unusable",
            extra={"search_id": str(search_id), "error": str(exc)[:500]},
        )
        raise HTTPException(status_code=404, detail="Search not found") from exc


async def _replay_search(
    db: AsyncSession, stored: Search, settings: Settings
) -> SearchReplayResponse:
    snapshot = stored.result_snapshot
    scholarship_ids = {item["scholarship_id"] for item in snapshot["data"]}
    published_ids: set[str] = set()
    if scholarship_ids:
        published_ids = {
            str(row)
            for row in await db.scalars(
                select(Scholarship.scholarship_id).where(
                    Scholarship.scholarship_id.in_(uuid.UUID(sid) for sid in scholarship_ids),
                    Scholarship.lifecycle_state == RecordState.published,
                )
            )
        }
    data = [item for item in snapshot["data"] if item["scholarship_id"] in published_ids]
    next_cursor = (
        encode_cursor(
            stored.requested_limit,
            stored.filter_digest,
            stored.search_id,
            stored.requested_limit,
            settings.cursor_secret,
        )
        if snapshot["pagination"]["has_next_page"]
        else None
    )
    return SearchReplayResponse(
        data=data,
        next_cursor=next_cursor,
        meta=ReplaySearchMeta(
            search_id=stored.search_id,
            response_id=stored.id,
            evaluated_at=stored.evaluated_at,
            match_policy_version=stored.match_policy_version,
            taxonomy_version=stored.taxonomy_version,
            confirmed_counts=snapshot["meta"].get("confirmed_counts"),
            possible_match_count=snapshot["meta"].get("possible_match_count"),
            warnings=snapshot["meta"]["warnings"],
        ),
        filters=stored.filters,
    )


@router.post("/search", response_model=SearchResponse)
async def search(
    payload: SearchRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> SearchResponse:
    settings = get_settings()
    # Key on the client address, not the cookie: an unauthenticated caller
    # chooses its own cookie value and could mint a fresh bucket per request.
    limiter_key = request.client.host if request.client else "unknown"
    if not search_limiter.allow(limiter_key, settings.api_rate_limit_per_minute):
        raise HTTPException(
            status_code=429, detail="Search rate limit exceeded", headers={"Retry-After": "60"}
        )
    evaluated_at = datetime.now(UTC)
    started = perf_counter()
    countries = await load_vocabulary(db)
    try:
        (
            origin,
            destinations,
            uncovered_destinations,
            degrees,
            field,
            accepted_fields,
        ) = normalize_search_filters(
            payload.origin_country,
            payload.target_countries,
            payload.program_levels,
            payload.field,
            countries,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    warnings: list[str] = []
    if uncovered_destinations:
        # Never refuse the whole search because one requested destination
        # among several isn't covered yet - run it for whichever are, and say
        # plainly which ones weren't, rather than silently returning fewer
        # results than requested with no explanation.
        warnings.append(f"no_verified_coverage:{','.join(sorted(uncovered_destinations))}")
    profile = SearchProfile(origin, destinations, degrees, accepted_fields)
    filters = {
        "origin_country": origin,
        "target_countries": sorted(destinations),
        "program_levels": sorted(degrees),
        "field": field,
    }
    session = await get_or_create_session(db, response, request.cookies.get(SESSION_COOKIE))
    digest = filter_digest(filters)
    # A fresh submission starts a new logical search; a page request keeps the
    # one its cursor carries, so pagination is not counted as several searches.
    offset = 0
    search_id = new_uuid7()
    if payload.cursor:
        try:
            cursor_state = decode_cursor(
                payload.cursor, digest, payload.limit, settings.cursor_secret
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        offset, search_id = cursor_state.offset, cursor_state.search_id
    result = await db.execute(
        select(ScholarshipCycle)
        .join(ScholarshipCycle.scholarship)
        .where(ScholarshipCycle.scholarship.has(lifecycle_state=RecordState.published))
        .options(selectinload(ScholarshipCycle.scholarship).selectinload(Scholarship.provider))
        .order_by(ScholarshipCycle.cycle_id)
        .limit(PUBLISHED_CYCLE_SCAN_LIMIT + 1)
    )
    rows = result.scalars().all()
    if len(rows) > PUBLISHED_CYCLE_SCAN_LIMIT:
        # Matching happens in Python, so the index has outgrown one scan. Say so
        # rather than quietly returning a subset as though it were complete.
        rows = rows[:PUBLISHED_CYCLE_SCAN_LIMIT]
        warnings.append("index_scan_truncated")
        logger.warning(
            "search_scan_truncated",
            extra={"request_id": getattr(request.state, "request_id", "")},
        )
    matched: list[SearchResult] = [
        result
        for row in rows
        if (decision := evaluate_match(profile, row.facts or {})) is not None
        and (result := _search_result(row, decision, evaluated_at)) is not None
    ]
    status_rank = {"open": 0, "closing_soon": 1, "likely_to_open": 2}
    # Confirmed matches outrank possible ones inside a status group. The
    # previous key sorted by negative caveat count, which put the
    # eligibility-uncertain records first.
    matched.sort(
        key=lambda item: (
            status_rank.get(item.status, 9),
            0 if item.fit == "confirmed" else 1,
            _result_sort_value(item, evaluated_at),
            str(item.cycle_id),
        )
    )
    confirmed_counts: dict[str, int] = {}
    for item in matched:
        if item.fit == "confirmed":
            confirmed_counts[item.status] = confirmed_counts.get(item.status, 0) + 1
    possible_match_count = sum(item.fit == "possible" for item in matched)
    data = matched[offset : offset + payload.limit]
    has_next_page = offset + payload.limit < len(matched)
    next_cursor = (
        encode_cursor(
            offset + payload.limit, digest, search_id, payload.limit, settings.cursor_secret
        )
        if has_next_page
        else None
    )
    page_number = offset // payload.limit + 1
    snapshot = build_result_snapshot(
        [item.model_dump() for item in data],
        evaluated_at=evaluated_at,
        match_policy_version=MATCH_POLICY_VERSION,
        taxonomy_version=TAXONOMY.version,
        page_number=page_number,
        requested_limit=payload.limit,
        total_match_count=len(matched),
        has_next_page=has_next_page,
        warnings=warnings,
        confirmed_counts=confirmed_counts,
        possible_match_count=possible_match_count,
    )
    stored = await record_search_response(
        db,
        session=session,
        search_id=search_id,
        filters=filters,
        filter_digest=digest,
        snapshot=snapshot,
        evaluated_at=evaluated_at,
        page_number=page_number,
        requested_limit=payload.limit,
        returned_count=len(data),
        total_match_count=len(matched),
        duration_ms=round((perf_counter() - started) * 1000),
    )
    if page_number == 1:
        # Only the first response of a logical search is a completed search.
        # Later pages must not inflate the funnel, and a re-requested page one
        # must not emit a second event, so the event is keyed on the search.
        await enqueue_analytics_event(
            db,
            event_type="scholarship_search_completed",
            dedupe_key=f"search_completed:{search_id}",
            payload={
                "search_id": str(search_id),
                "response_id": str(stored.id),
                "filters": filters,
                "total_match_count": len(matched),
                "confirmed_counts": confirmed_counts,
                "possible_match_count": possible_match_count,
                "match_policy_version": MATCH_POLICY_VERSION,
                "taxonomy_version": TAXONOMY.version,
            },
        )
    # The row and its event commit with the response. get_db commits on a clean
    # return, so a failure here surfaces as an error rather than a success whose
    # history was never durably recorded.
    return SearchResponse(
        data=data,
        next_cursor=next_cursor,
        meta=SearchMeta(
            search_id=search_id,
            response_id=stored.id,
            evaluated_at=evaluated_at,
            match_policy_version=MATCH_POLICY_VERSION,
            taxonomy_version=TAXONOMY.version,
            confirmed_counts=confirmed_counts,
            possible_match_count=possible_match_count,
            warnings=warnings,
        ),
    )


async def _fetch_published_cycle_row(identifier: str, db: AsyncSession) -> ScholarshipCycle | None:
    try:
        scholarship_id = uuid.UUID(identifier)
        predicate = ScholarshipCycle.scholarship_id == scholarship_id
    except ValueError:
        predicate = Scholarship.slug == identifier
    result = await db.execute(
        select(ScholarshipCycle)
        .join(ScholarshipCycle.scholarship)
        .where(
            predicate,
            Scholarship.lifecycle_state == RecordState.published,
        )
        .options(selectinload(ScholarshipCycle.scholarship).selectinload(Scholarship.provider))
        .limit(1)
    )
    return result.scalars().first()


async def _scholarship_detail(identifier: str, db: AsyncSession) -> ScholarshipDetailResponse:
    row = await _fetch_published_cycle_row(identifier, db)
    if row is None:
        raise HTTPException(status_code=404, detail="Scholarship not found")
    return _detail(row)


@router.get("/scholarships/{identifier}", response_model=ScholarshipDetailResponse)
async def scholarship_detail(
    identifier: str, db: AsyncSession = Depends(get_db)
) -> ScholarshipDetailResponse:
    return await _scholarship_detail(identifier, db)


match_explanation_limiter = InMemoryRateLimiter()
#: A cache miss is a real paid AI Router call, unlike a free DB search - a
#: much tighter cap than search's is deliberate, not an oversight.
MATCH_EXPLANATION_PER_MINUTE = 10


@router.post("/scholarships/{identifier}", response_model=ScholarshipDetailResponse)
async def scholarship_detail_with_explanation(
    identifier: str,
    payload: MatchProfileRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ScholarshipDetailResponse:
    """Same detail as `GET`, plus a `match_explanation` for this searcher's
    profile against this one scholarship - never the other way around, so a
    bare shared link (`GET`, no profile) stays free of any AI Router call.

    The explanation elaborates on the deterministic match decision
    (`evaluate_match`'s `fit`/`reason_codes`/`caveats`) rather than
    re-deriving one - per the automation boundary, AI explains a match, it
    never computes one. A profile that doesn't deterministically match this
    cycle at all (wrong level, ineligible origin, wrong field) gets the
    plain detail response with no explanation - there's nothing true to
    explain about a non-match, so nothing is asked of the router.
    """
    limiter_key = request.client.host if request.client else "unknown"
    if not match_explanation_limiter.allow(limiter_key, MATCH_EXPLANATION_PER_MINUTE):
        raise HTTPException(
            status_code=429,
            detail="Match-explanation rate limit exceeded",
            headers={"Retry-After": "60"},
        )
    row = await _fetch_published_cycle_row(identifier, db)
    if row is None:
        raise HTTPException(status_code=404, detail="Scholarship not found")
    detail = _detail(row)
    countries = await load_vocabulary(db)
    try:
        origin = countries.origin(payload.origin_country)
        degrees = frozenset(TAXONOMY.degree(value) for value in payload.program_levels)
        accepted_fields = (
            TAXONOMY.narrow_fields_under(TAXONOMY.broad_field(payload.field))
            if payload.field
            else None
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # detail.facts is the same sanitized dict _detail() already built via
    # _derive_facts (destinations, origin_mode, field_mode, evidence_fresh,
    # etc.) - use it here too, not the raw stored facts, so the match
    # decision (and the AI explanation grounded in it) can never disagree
    # with what this same response's own facts field shows. Computing the
    # decision from a raw origin_mode/field_mode this response has already
    # clamped away (e.g. "Restricted" clamped to "unknown") could otherwise
    # return fit="confirmed" right next to facts.origin_mode == "unknown".
    profile = SearchProfile(origin, frozenset(detail.destinations), degrees, accepted_fields)
    decision = evaluate_match(profile, detail.facts)
    if decision is None:
        return detail
    detail.match_explanation = await get_match_explanation(
        db,
        cycle=row,
        facts=detail.facts,
        origin_country=origin,
        program_levels=sorted(degrees),
        field=payload.field,
        decision=decision,
    )
    return detail


async def database_ready(db: AsyncSession) -> bool:
    """Confirm the database answers, under a bound.

    An unbounded probe turns a stalled database into a hanging readiness check,
    which reads as healthy to a platform waiting on the response.
    """
    await asyncio.wait_for(
        db.execute(text("SELECT 1")), timeout=get_settings().db_connect_timeout_seconds
    )
    return True
