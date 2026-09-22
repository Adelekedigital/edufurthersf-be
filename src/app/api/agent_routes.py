"""The Agent integration surface.

Six routes, behind their own credential. The Agent can read discoveries,
submit split candidates, attach evidence, ask for a review and record its
outcome. It cannot decide a review, create a scholarship, publish a cycle or
withdraw one - those need the admin token and are not reachable from here.

That separation is the point of a second token rather than a second use of
the existing one: this service's automation boundary says a model may
propose facts and drafts but must not verify or publish, and a credential
that grants the whole admin surface would leave that boundary resting
entirely on the Agent's good behaviour.
"""

import hmac
import logging
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.agent_schemas import (
    AgentDiscoveryListResponse,
    AgentDiscoveryRead,
    AgentReviewRequest,
    AgentReviewResponse,
    AgentRunRead,
    AgentRunRequest,
    CandidateSubmissionRequest,
    CandidateSubmissionResponse,
    EvidenceSubmissionRequest,
    EvidenceSubmissionResponse,
)
from app.core.errors import problem
from app.domain.models import Discovery, Source, SourcePage
from app.infra.agent_integration import (
    InactiveSource,
    list_discoveries,
    load_discovery_context,
    record_evidence,
    record_run,
    request_review,
    submit_candidates,
)
from app.infra.db import get_db

logger = logging.getLogger("app.api.agent")

#: The queue's default when the Agent does not supply one. Matches the
#: "no identity candidate" default in domain/linking.py, so an
#: Agent-requested task does not jump ahead of the product's own.
DEFAULT_REVIEW_PRIORITY = 100


async def require_agent_service(x_service_token: str | None = Header(default=None)) -> None:
    """Authenticate the Agent service.

    Constant time, and fails closed when unconfigured - the same shape as
    `require_internal_service`, deliberately, because it is the same threat.
    A separate secret so that the Agent holding a credential does not mean
    the Agent holding publish rights, and so either can be rotated alone.
    """
    from app.core.config import get_settings

    expected = get_settings().agent_service_token
    if not expected or not hmac.compare_digest(x_service_token or "", expected):
        raise HTTPException(status_code=401, detail="Agent service authentication required")


router = APIRouter(
    prefix="/internal/agent",
    tags=["agent"],
    dependencies=[Depends(require_agent_service)],
)


def _to_read(discovery: Discovery, page: SourcePage, source: Source) -> AgentDiscoveryRead:
    return AgentDiscoveryRead(
        discovery_id=discovery.discovery_id,
        source_page_id=page.page_id,
        source_id=source.source_id,
        source_name=source.name,
        source_url=page.final_url or page.normalized_url,
        approved_domains=list(source.approved_domains or []),
        authority_grade=source.authority_grade,
        raw_title=discovery.raw_title,
        raw_excerpt=discovery.raw_excerpt,
        processing_state=discovery.processing_state,
        normalized_identity_key=discovery.normalized_identity_key,
        extracted_facts=discovery.extracted_facts,
        ai_extracted_facts=discovery.ai_extracted_facts,
        supersedes_discovery_id=discovery.supersedes_discovery_id,
        duplicate_of_discovery_id=discovery.duplicate_of_discovery_id,
        split_from_discovery_id=discovery.split_from_discovery_id,
        canonical_scholarship_id=discovery.canonical_scholarship_id,
        source_posted_at=discovery.source_posted_at,
        created_at=discovery.created_at,
    )


@router.get("/discoveries", response_model=AgentDiscoveryListResponse)
async def read_discoveries(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    after: uuid.UUID | None = Query(default=None),
    workflow_version: str | None = Query(default=None, max_length=64),
    unprocessed_only: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
) -> AgentDiscoveryListResponse | JSONResponse:
    """Work intake.

    `unprocessed_only` excludes discoveries already run under
    `workflow_version`, so bumping the version deliberately makes them
    eligible again rather than being mistaken for duplicates.
    """
    if unprocessed_only and not workflow_version:
        # The filter silently did nothing in this combination, so a caller
        # asking for unprocessed work with no version got the whole table
        # back and reprocessed every discovery - at five model calls each.
        # Failing loudly is much cheaper than that.
        return problem(
            request,
            status=422,
            code="WORKFLOW_VERSION_REQUIRED",
            title="Unprocessable Content",
            detail="workflow_version is required when unprocessed_only is true",
        )
    rows = await list_discoveries(
        db,
        limit=limit,
        after=after,
        workflow_version=workflow_version,
        unprocessed_only=unprocessed_only,
    )
    items = [_to_read(discovery, page, source) for discovery, page, source in rows]
    # Only a full page can have more after it; a short page is the last one.
    next_cursor = items[-1].discovery_id if len(items) == limit else None
    return AgentDiscoveryListResponse(items=items, next_cursor=next_cursor)


@router.get("/discoveries/{discovery_id}", response_model=AgentDiscoveryRead)
async def read_discovery(
    request: Request, discovery_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> AgentDiscoveryRead | JSONResponse:
    context = await load_discovery_context(db, discovery_id)
    if context is None:
        return problem(
            request,
            status=404,
            code="DISCOVERY_NOT_FOUND",
            title="Not Found",
            detail="No such discovery",
        )
    return _to_read(context.discovery, context.page, context.source)


@router.post("/candidates", response_model=CandidateSubmissionResponse)
async def submit_split_candidates(
    request: Request, payload: CandidateSubmissionRequest, db: AsyncSession = Depends(get_db)
) -> CandidateSubmissionResponse | JSONResponse:
    """Record awards split out of a list page as distinct discoveries.

    Each becomes a real Discovery and enters the ordinary pipeline, so it
    gets the same identity linking, duplicate detection and review-task
    uniqueness a feed-imported row would. Unusable candidates are reported
    per item rather than failing the batch - one bad row must not discard
    the nine good ones alongside it.
    """
    try:
        result = await submit_candidates(db, payload)
    except InactiveSource:
        return problem(
            request,
            status=409,
            code="SOURCE_INACTIVE",
            title="Conflict",
            detail="The parent discovery's source has been deactivated",
        )
    if result is None:
        return problem(
            request,
            status=404,
            code="DISCOVERY_NOT_FOUND",
            title="Not Found",
            detail="No such parent discovery",
        )
    return result


@router.post("/candidates/{discovery_id}/evidence", response_model=EvidenceSubmissionResponse)
async def attach_evidence(
    request: Request,
    discovery_id: uuid.UUID,
    payload: EvidenceSubmissionRequest,
    db: AsyncSession = Depends(get_db),
) -> EvidenceSubmissionResponse | JSONResponse:
    if await load_discovery_context(db, discovery_id) is None:
        return problem(
            request,
            status=404,
            code="DISCOVERY_NOT_FOUND",
            title="Not Found",
            detail="No such discovery",
        )
    recorded, duplicates = await record_evidence(db, discovery_id, payload)
    return EvidenceSubmissionResponse(
        discovery_id=discovery_id, recorded=recorded, duplicates=duplicates
    )


@router.post("/candidates/{discovery_id}/review", response_model=AgentReviewResponse)
async def ask_for_review(
    request: Request,
    discovery_id: uuid.UUID,
    payload: AgentReviewRequest,
    db: AsyncSession = Depends(get_db),
) -> AgentReviewResponse | JSONResponse:
    """Open a review task, once.

    Can open a task; cannot close one, and cannot write the deterministic
    `draft_recommendation` that `prepare_review` produces. The Agent's own
    proposal belongs on `agent_runs.recommendation`, where a reviewer can
    weigh it separately rather than being handed one merged opinion.
    """
    if await load_discovery_context(db, discovery_id) is None:
        return problem(
            request,
            status=404,
            code="DISCOVERY_NOT_FOUND",
            title="Not Found",
            detail="No such discovery",
        )
    review_task_id, created = await request_review(
        db,
        discovery_id,
        reason=payload.reason,
        priority=payload.priority or DEFAULT_REVIEW_PRIORITY,
    )
    if review_task_id is None:
        # Nothing inserted and nothing open found. The insert only conflicts
        # when an open task exists, so this is the narrow race where another
        # writer resolved that task in between - not "already decided". A
        # resolved task does not block a new one, here or in link_discovery:
        # uq_review_tasks_open_per_discovery is partial, covering open tasks
        # only, so a re-crawl that changes the facts can earn a fresh look.
        return problem(
            request,
            status=409,
            code="REVIEW_ALREADY_RESOLVED",
            title="Conflict",
            detail="The review task was resolved concurrently; retry",
        )
    return AgentReviewResponse(
        discovery_id=discovery_id, review_task_id=review_task_id, created=created
    )


@router.post("/runs", response_model=AgentRunRead)
async def record_agent_run(
    request: Request, payload: AgentRunRequest, db: AsyncSession = Depends(get_db)
) -> AgentRunRead | JSONResponse:
    """Record a workflow run's outcome.

    Recorded, not acted on. `AUTO_CHECK_ELIGIBLE` is an input to this
    service's existing deterministic gates; nothing in `auto_approval.py`
    reads this table, and writing one here publishes nothing.
    """
    if await load_discovery_context(db, payload.discovery_id) is None:
        return problem(
            request,
            status=404,
            code="DISCOVERY_NOT_FOUND",
            title="Not Found",
            detail="No such discovery",
        )
    run = await record_run(db, payload)
    logger.info(
        "agent_run_recorded",
        extra={
            "discovery_id": str(payload.discovery_id),
            "workflow_version": payload.workflow_version,
            "outcome": payload.agent_outcome,
        },
    )
    return AgentRunRead.model_validate(run, from_attributes=True)
