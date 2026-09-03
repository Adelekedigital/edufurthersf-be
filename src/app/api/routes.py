import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Literal, cast

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.detail_schemas import ScholarshipDetailResponse
from app.api.ingestion_schemas import FeedImportRequest, FeedImportResponse
from app.api.job_schemas import JobRequest, JobResponse
from app.api.join_schemas import JoinIntentRequest, JoinIntentResponse
from app.api.review_schemas import ReviewDecisionRequest, ReviewDecisionResponse
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
from app.core.rate_limit import InMemoryRateLimiter
from app.domain.matching import SearchProfile, evaluate_match
from app.domain.models import JoinRequest, RecordState, Scholarship, ScholarshipCycle, Search
from app.domain.status import evaluate_public_status
from app.domain.taxonomy import TAXONOMY, normalize_search_filters
from app.infra.core_client import CoreJoinClient
from app.infra.db import get_db
from app.infra.ingestion import import_feed_records
from app.infra.jobs import enqueue_job
from app.infra.qstash import ALLOWED_JOB_KINDS, QStashVerificationConfig, QStashVerifier
from app.infra.reviews import decide_review
from app.infra.sessions import get_or_create_session, record_search

logger = logging.getLogger("app.api")
router = APIRouter()
search_limiter = InMemoryRateLimiter()


async def require_internal_service(x_service_token: str | None = Header(default=None)) -> None:
    from app.core.config import get_settings

    expected = get_settings().internal_service_token
    if not expected or x_service_token != expected:
        raise HTTPException(status_code=401, detail="Internal service authentication required")


@router.post(
    "/internal/import/feed",
    response_model=FeedImportResponse,
    dependencies=[Depends(require_internal_service)],
)
async def import_feed(
    payload: FeedImportRequest, db: AsyncSession = Depends(get_db)
) -> FeedImportResponse:
    accepted, duplicates, rejected = await import_feed_records(db, payload.records)
    return FeedImportResponse(accepted=accepted, duplicates=duplicates, rejected=rejected)


def _qstash_destination(request: Request, kind: str | None = None) -> str:
    """Return the URL QStash signed as `sub`.

    `request.url` only reconstructs that URL when the app is reached directly;
    a platform proxy leaves the scheme and host rewritten, so the configured
    public callback URL wins whenever it is set.
    """
    configured = get_settings().qstash_expected_destination
    if not configured:
        return str(request.url)
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
async def taxonomies() -> TaxonomiesResponse:
    return TaxonomiesResponse(
        version=TAXONOMY.version,
        countries=[
            TaxonomyItem(code=code, label=label) for code, label in TAXONOMY.countries.items()
        ],
        degrees=[TaxonomyItem(code=code, label=label) for code, label in TAXONOMY.degrees.items()],
        fields=[TaxonomyItem(code=code, label=label) for code, label in TAXONOMY.fields.items()],
    )


@router.post("/join-intents", response_model=JoinIntentResponse)
async def create_join_intent(
    payload: JoinIntentRequest, db: AsyncSession = Depends(get_db)
) -> JoinIntentResponse:
    """Create a consented, idempotent handoff from Finder to the Core product."""
    if not payload.consent:
        raise HTTPException(status_code=422, detail="Consent is required")
    settings = get_settings()
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
    if not return_url.startswith(settings.core_allowed_return_url_prefix or ""):
        raise HTTPException(status_code=422, detail="Return URL is not allowed")
    search = await db.scalar(select(Search).where(Search.search_id == payload.search_id))
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
    limiter_key = request.cookies.get("finder_session") or (
        request.client.host if request.client else "unknown"
    )
    if not search_limiter.allow(limiter_key, settings.api_rate_limit_per_minute):
        raise HTTPException(status_code=429, detail="Search rate limit exceeded")
    evaluated_at = datetime.now(UTC)
    try:
        origin, destinations, degree, field = normalize_search_filters(
            payload.origin_country, payload.target_countries, payload.program_level, payload.field
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
    session = await get_or_create_session(db, response, request.cookies.get("finder_session"))
    search_id = await record_search(db, session, filters)
    filter_digest = hashlib.sha256(
        json.dumps(filters, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    offset = 0
    if payload.cursor:
        try:
            offset = decode_cursor(payload.cursor, filter_digest, settings.cursor_secret)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = await db.execute(
        select(ScholarshipCycle)
        .join(ScholarshipCycle.scholarship)
        .where(ScholarshipCycle.scholarship.has(lifecycle_state=RecordState.published))
        .options(selectinload(ScholarshipCycle.scholarship).selectinload(Scholarship.provider))
        .limit(150)
    )
    rows = result.scalars().all()
    matched: list[SearchResult] = [
        SearchResult(
            scholarship_id=row.scholarship_id,
            cycle_id=row.cycle_id,
            name=row.scholarship.name if row.scholarship else "",
            provider=row.scholarship.provider.name
            if row.scholarship and row.scholarship.provider
            else "",
            status=row.public_status.value,
            fit=cast(Literal["confirmed", "possible"], decision.fit),
            official_url=row.official_cycle_url,
            last_verified_at=row.last_verified_at,
            caveats=list(decision.caveats),
        )
        for row in rows
        if (decision := evaluate_match(profile, row.facts)) is not None
    ]
    status_rank = {"open_verified": 0, "expected_to_reopen": 1, "status_unknown": 2}
    matched.sort(
        key=lambda item: (
            status_rank.get(item.status, 9),
            -len(item.caveats),
            str(item.scholarship_id),
        )
    )
    data = matched[offset : offset + payload.limit]
    next_cursor = (
        encode_cursor(offset + payload.limit, filter_digest, settings.cursor_secret)
        if offset + payload.limit < len(matched)
        else None
    )
    return SearchResponse(
        data=data,
        next_cursor=next_cursor,
        meta=SearchMeta(
            search_id=search_id,
            evaluated_at=evaluated_at,
            confirmed_counts={},
            possible_match_count=sum(item.fit == "possible" for item in matched),
            warnings=[],
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
    await db.execute(text("SELECT 1"))
    return True
