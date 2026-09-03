import asyncio
import hmac
import logging
import uuid
from datetime import UTC, datetime
from time import perf_counter
from typing import Literal, cast

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.detail_schemas import ScholarshipDetailResponse
from app.api.ingestion_schemas import FeedImportRequest, FeedImportResponse
from app.api.job_schemas import JobRequest, JobResponse
from app.api.join_schemas import JoinIntentRequest, JoinIntentResponse
from app.api.review_schemas import (
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    ReviewQueueResponse,
    ReviewTaskSummary,
    WithdrawRequest,
    WithdrawResponse,
)
from app.api.schemas import (
    SearchMeta,
    SearchRequest,
    SearchResponse,
    SearchResult,
    TaxonomiesResponse,
    TaxonomyItem,
)
from app.core.config import get_settings
from app.core.cursors import decode_cursor, encode_cursor
from app.core.ids import new_uuid7
from app.core.rate_limit import InMemoryRateLimiter
from app.domain.matching import MatchDecision, SearchProfile, evaluate_match
from app.domain.models import (
    Discovery,
    JoinRequest,
    RecordState,
    ReviewTask,
    Scholarship,
    ScholarshipCycle,
    Search,
)
from app.domain.return_urls import is_allowed_return_url
from app.domain.snapshots import build_result_snapshot
from app.domain.status import evaluate_public_status
from app.domain.taxonomy import TAXONOMY, normalize_search_filters
from app.infra.core_client import CoreJoinClient
from app.infra.countries import load_vocabulary
from app.infra.db import get_db
from app.infra.ingestion import import_feed_records
from app.infra.jobs import enqueue_job
from app.infra.outbox import enqueue_analytics_event
from app.infra.qstash import ALLOWED_JOB_KINDS, QStashVerificationConfig, QStashVerifier
from app.infra.reviews import decide_review
from app.infra.sessions import (
    SESSION_COOKIE,
    filter_digest,
    get_or_create_session,
    record_search_response,
)
from app.infra.withdrawals import withdraw_scholarship

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
MATCH_POLICY_VERSION = "match-v1"
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


async def _enqueue(kind: str, job_request: JobRequest, db: AsyncSession) -> JobResponse:
    if kind not in ALLOWED_JOB_KINDS:
        raise HTTPException(status_code=404, detail="Unknown job kind")
    job, created = await enqueue_job(db, kind, job_request.dedupe_key, job_request.payload)
    return JobResponse(job_id=job.job_id, state=job.state, created=created)


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


def _search_result(
    row: ScholarshipCycle, decision: MatchDecision, evaluated_at: datetime
) -> SearchResult:
    """Build one public result, re-deriving status at read time.

    A stored `open_verified` whose deadline or freshness boundary has passed
    must not be returned as open just because no sweep has run yet; search
    previously returned the stored value untouched while the detail endpoint
    re-evaluated it, so the two disagreed and search could claim a closed
    award was open.
    """
    facts = row.facts or {}
    deadline_at = facts.get("deadline_at")
    status = evaluate_public_status(
        row.public_status,
        deadline_at=datetime.fromisoformat(deadline_at) if deadline_at else None,
        status_valid_until=row.status_valid_until,
        now=evaluated_at,
    )
    caveats = list(decision.caveats)
    if status != row.public_status:
        caveats.append("Current status evidence requires re-verification.")
    return SearchResult(
        scholarship_id=row.scholarship_id,
        cycle_id=row.cycle_id,
        name=row.scholarship.name if row.scholarship else "",
        provider=row.scholarship.provider.name
        if row.scholarship and row.scholarship.provider
        else "",
        status=status.value,
        fit=cast(Literal["confirmed", "possible"], decision.fit),
        official_url=row.official_cycle_url,
        last_verified_at=row.last_verified_at,
        caveats=caveats,
    )


@router.get(
    "/internal/admin/reviews",
    response_model=ReviewQueueResponse,
    dependencies=[Depends(require_internal_service)],
)
async def review_queue(
    state: Literal["open", "resolved"] = "open",
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> ReviewQueueResponse:
    """The reviewer's work list, highest priority and oldest first."""
    rows = list(
        await db.execute(
            select(ReviewTask, Discovery.raw_title)
            .outerjoin(Discovery, Discovery.discovery_id == ReviewTask.discovery_id)
            .where(ReviewTask.state == state)
            .order_by(ReviewTask.priority, ReviewTask.created_at)
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
                raw_title=raw_title,
                created_at=task.created_at,
            )
            for task, raw_title in rows
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


def _detail(row: ScholarshipCycle) -> ScholarshipDetailResponse:
    facts = row.facts or {}
    deadline_at = facts.get("deadline_at")
    status = evaluate_public_status(
        row.public_status,
        deadline_at=datetime.fromisoformat(deadline_at) if deadline_at else None,
        status_valid_until=row.status_valid_until,
    )
    return ScholarshipDetailResponse(
        scholarship_id=row.scholarship_id,
        cycle_id=row.cycle_id,
        name=row.scholarship.name,
        provider=row.scholarship.provider.name,
        status=status.value,
        status_valid_until=row.status_valid_until,
        official_url=row.official_cycle_url,
        facts=facts,
        last_verified_at=row.last_verified_at,
        caveats=[]
        if status == row.public_status
        else ["Current status evidence requires re-verification."],
    )


@router.get("/taxonomies", response_model=TaxonomiesResponse)
async def taxonomies(db: AsyncSession = Depends(get_db)) -> TaxonomiesResponse:
    """The vocabularies a search form is built from.

    Countries come from the mirror of Core's catalogue; destinations are the
    subset with verified coverage, returned separately so the form can offer
    every origin while limiting where a search can be run.
    """
    countries = await load_vocabulary(db)
    return TaxonomiesResponse(
        version=TAXONOMY.version,
        countries=[
            TaxonomyItem(code=code, label=label) for code, label in sorted(countries.names.items())
        ],
        destinations=[
            TaxonomyItem(code=code, label=countries.names[code])
            for code in sorted(countries.destinations)
            if code in countries.names
        ],
        degrees=[TaxonomyItem(code=code, label=label) for code, label in TAXONOMY.degrees.items()],
        fields=[TaxonomyItem(code=code, label=label) for code, label in TAXONOMY.fields.items()],
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
        raise HTTPException(status_code=429, detail="Join request rate limit exceeded")
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


@router.post("/search", response_model=SearchResponse)
async def search(
    payload: SearchRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> SearchResponse:
    settings = get_settings()
    # Key on the client address, not the cookie: an unauthenticated caller
    # chooses its own cookie value and could mint a fresh bucket per request.
    limiter_key = request.client.host if request.client else "unknown"
    if not search_limiter.allow(limiter_key, settings.api_rate_limit_per_minute):
        raise HTTPException(status_code=429, detail="Search rate limit exceeded")
    evaluated_at = datetime.now(UTC)
    started = perf_counter()
    countries = await load_vocabulary(db)
    try:
        origin, destinations, degree, field = normalize_search_filters(
            payload.origin_country,
            payload.target_countries,
            payload.program_level,
            payload.field,
            countries,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    profile = SearchProfile(origin, destinations, degree, field)
    filters = {
        "origin_country": origin,
        "target_countries": sorted(destinations),
        "program_level": degree,
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
            cursor_state = decode_cursor(payload.cursor, digest, settings.cursor_secret)
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
    warnings: list[str] = []
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
        _search_result(row, decision, evaluated_at)
        for row in rows
        if (decision := evaluate_match(profile, row.facts)) is not None
    ]
    status_rank = {"open_verified": 0, "expected_to_reopen": 1, "status_unknown": 2}
    # Confirmed matches outrank possible ones inside a status group. The
    # previous key sorted by negative caveat count, which put the
    # eligibility-uncertain records first.
    fit_rank = {"confirmed": 0, "possible": 1}
    matched.sort(
        key=lambda item: (
            fit_rank.get(item.fit, 9),
            status_rank.get(item.status, 9),
            str(item.scholarship_id),
        )
    )
    confirmed_counts: dict[str, int] = {}
    for item in matched:
        if item.fit == "confirmed":
            confirmed_counts[item.status] = confirmed_counts.get(item.status, 0) + 1
    data = matched[offset : offset + payload.limit]
    has_next_page = offset + payload.limit < len(matched)
    next_cursor = (
        encode_cursor(offset + payload.limit, digest, search_id, settings.cursor_secret)
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
                "possible_match_count": sum(item.fit == "possible" for item in matched),
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
            confirmed_counts=confirmed_counts,
            possible_match_count=sum(item.fit == "possible" for item in matched),
            warnings=warnings,
        ),
    )


async def _scholarship_detail(identifier: str, db: AsyncSession) -> ScholarshipDetailResponse:
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
    row = result.scalars().first()
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Scholarship not found")
    return _detail(row)


@router.get("/scholarships/{identifier}", response_model=ScholarshipDetailResponse)
async def scholarship_detail(
    identifier: str, db: AsyncSession = Depends(get_db)
) -> ScholarshipDetailResponse:
    return await _scholarship_detail(identifier, db)


async def database_ready(db: AsyncSession) -> bool:
    """Confirm the database answers, under a bound.

    An unbounded probe turns a stalled database into a hanging readiness check,
    which reads as healthy to a platform waiting on the response.
    """
    await asyncio.wait_for(
        db.execute(text("SELECT 1")), timeout=get_settings().db_connect_timeout_seconds
    )
    return True
