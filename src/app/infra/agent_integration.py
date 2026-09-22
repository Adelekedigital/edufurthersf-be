"""Persistence for the Agent integration surface.

The Agent proposes; this module records. Nothing here sets a ReviewTask's
state or resolution, creates a Scholarship, or publishes a cycle - those
remain behind the admin token and the existing review routes, and
`auto_approval.py` is untouched.

Split candidates deliberately reuse the ordinary pipeline rather than a
parallel one: each becomes a real Discovery and gets `normalize_discovery`
and `link_canonical` enqueued, so identity keys, duplicate lineage and
review-task uniqueness all work exactly as they do for a feed import.
Inventing a second path would mean re-solving every problem this one
already solved.
"""

import hashlib
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Row, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.agent_schemas import (
    AgentRunRequest,
    CandidateResult,
    CandidateSubmission,
    CandidateSubmissionRequest,
    CandidateSubmissionResponse,
    EvidenceSubmissionRequest,
)
from app.domain.ingestion import prepare_candidate
from app.domain.models import (
    AgentRun,
    Discovery,
    DiscoveryEvidence,
    ProcessingJob,
    ReviewTask,
    Source,
    SourcePage,
)
from app.domain.normalization import normalize_discovery

# Same-layer helpers. Private by name because nothing outside `infra` should
# reach for them, which this is not.
from app.infra.ingestion import _dispatch_pending_jobs, _PendingJob

logger = logging.getLogger("app.infra.agent_integration")


class InactiveSource(RuntimeError):
    """The parent's Source has been switched off.

    Distinct from "no such parent" so the caller can tell a deactivated
    source from a missing one - they need different actions.
    """


@dataclass(frozen=True)
class DiscoveryContext:
    discovery: Discovery
    page: SourcePage
    source: Source


async def load_discovery_context(
    db: AsyncSession, discovery_id: uuid.UUID
) -> DiscoveryContext | None:
    row = (
        await db.execute(
            select(Discovery, SourcePage, Source)
            .join(SourcePage, SourcePage.page_id == Discovery.source_page_id)
            .join(Source, Source.source_id == SourcePage.source_id)
            .where(Discovery.discovery_id == discovery_id)
        )
    ).one_or_none()
    if row is None:
        return None
    return DiscoveryContext(*row)


async def list_discoveries(
    db: AsyncSession,
    *,
    limit: int,
    after: uuid.UUID | None,
    workflow_version: str | None,
    unprocessed_only: bool,
) -> Sequence[Row[tuple[Discovery, SourcePage, Source]]]:
    """Discoveries for the Agent to work through.

    Keyset pagination on `discovery_id` rather than an offset: the queue is
    written to while it is read, and an offset silently skips rows whenever
    an earlier one is inserted.

    `unprocessed_only` filters against `agent_runs` for the given workflow
    version, so bumping the version makes previously processed records
    eligible again - which is the whole point of versioning the run.
    """
    statement = (
        select(Discovery, SourcePage, Source)
        .join(SourcePage, SourcePage.page_id == Discovery.source_page_id)
        .join(Source, Source.source_id == SourcePage.source_id)
        .order_by(Discovery.discovery_id)
        .limit(limit)
    )
    if after is not None:
        statement = statement.where(Discovery.discovery_id > after)
    if unprocessed_only and workflow_version:
        run = aliased(AgentRun)
        statement = statement.outerjoin(
            run,
            (run.discovery_id == Discovery.discovery_id)
            & (run.workflow_version == workflow_version),
        ).where(run.run_id.is_(None))
    return (await db.execute(statement)).all()


async def submit_candidates(
    db: AsyncSession, payload: CandidateSubmissionRequest
) -> CandidateSubmissionResponse | None:
    """Turn extracted list items into real Discovery rows.

    Returns None when the parent does not exist, so the caller can 404.

    Two things this must get right, both of which a naive reuse of
    `import_feed_records` gets wrong:

    1. `supersedes_discovery_id` is never set. That function assigns it from
       the newest prior discovery on the same page, which for ten candidates
       split out of one blog post would chain them into ten revisions of one
       award instead of ten siblings.
    2. `split_from_discovery_id` records the parent, so the list page stays
       attached to everything taken from it.
    """
    context = await load_discovery_context(db, payload.parent_discovery_id)
    if context is None:
        return None
    if not context.source.active:
        # `Source.active` is this service's harvest kill switch, and
        # `import_feed_records` quarantines rows from an inactive source
        # rather than importing them. Without the same check here, an
        # operator who switched a source off could still have candidates
        # arrive under it through the Agent - the switch bypassed by a
        # side door.
        raise InactiveSource(str(context.source.source_id))

    parent_url = context.page.normalized_url
    results: list[CandidateResult] = []
    pending: list[_PendingJob] = []
    created = duplicates = rejected = 0

    for candidate in payload.candidates:
        outcome = await _submit_one(
            db,
            candidate=candidate,
            parent=context,
            parent_url=parent_url,
            pending=pending,
        )
        results.append(outcome)
        if outcome.status == "created":
            created += 1
        elif outcome.status == "duplicate":
            duplicates += 1
        else:
            rejected += 1

    await db.commit()
    # Only after the commit: dispatching first risks QStash delivering a
    # callback for a Discovery a rollback made never exist. This service
    # learned that one the hard way.
    if pending:
        await _dispatch_pending_jobs(pending)

    logger.info(
        "agent_candidates_submitted",
        extra={
            "parent_discovery_id": str(payload.parent_discovery_id),
            "created_count": created,
            "duplicate_count": duplicates,
            "rejected_count": rejected,
        },
    )
    return CandidateSubmissionResponse(
        parent_discovery_id=payload.parent_discovery_id,
        created=created,
        duplicates=duplicates,
        rejected=rejected,
        results=results,
    )


async def _submit_one(
    db: AsyncSession,
    *,
    candidate: CandidateSubmission,
    parent: DiscoveryContext,
    parent_url: str,
    pending: list[_PendingJob],
) -> CandidateResult:
    # A candidate with no link of its own is recorded against the parent's
    # page. That is not a fallback so much as the truth: the page is where
    # the claim was actually found.
    url = str(candidate.url) if candidate.url else parent_url
    try:
        prepared = prepare_candidate(url, candidate.title, candidate.excerpt)
    except ValueError as exc:
        return CandidateResult(
            title=candidate.title, discovery_id=None, status="rejected", reason=str(exc)
        )

    page = await db.scalar(
        select(SourcePage).where(
            SourcePage.source_id == parent.source.source_id,
            SourcePage.normalized_url == prepared.normalized_url,
        )
    )
    now = datetime.now(UTC)
    if page is None:
        page = SourcePage(
            source_id=parent.source.source_id,
            normalized_url=prepared.normalized_url,
            last_seen_at=now,
        )
        db.add(page)
        await db.flush()
    else:
        page.last_seen_at = now

    existing = await db.scalar(
        select(Discovery).where(
            Discovery.source_page_id == page.page_id,
            Discovery.content_hash == prepared.content_hash,
        )
    )
    if existing is not None:
        # Resubmitting the same run is idempotent. The content hash covers
        # url + title + excerpt, so this is the same candidate, not merely a
        # similar one.
        return CandidateResult(
            title=candidate.title, discovery_id=existing.discovery_id, status="duplicate"
        )

    normalized = normalize_discovery(prepared.title)
    excerpt = prepared.excerpt
    if candidate.heading:
        # Preserved in the excerpt rather than a column of its own: it is
        # provenance a reviewer needs to find the item on the page again,
        # and it belongs with the text it introduces.
        excerpt = f"[{candidate.heading}]\n{excerpt or ''}".strip()

    discovery = Discovery(
        source_page_id=page.page_id,
        content_hash=prepared.content_hash,
        raw_title=prepared.title,
        raw_excerpt=excerpt,
        normalized_identity_key=normalized.identity_key,
        processing_state="normalized",
        # Never supersedes: these are siblings of each other, not revisions.
        split_from_discovery_id=parent.discovery.discovery_id,
    )
    db.add(discovery)
    await db.flush()

    # Hashed rather than interpolated raw. A 500-character title yields a
    # ~500-character identity key, and `normalize:{uuid}:{key}` then exceeds
    # ProcessingJob.dedupe_key's String(500) - which raises at commit and
    # discards every valid candidate in the batch alongside the bad one.
    identity_digest = hashlib.sha256(normalized.identity_key.encode()).hexdigest()[:32]
    for kind, dedupe_key in (
        ("normalize_discovery", f"normalize:{discovery.discovery_id}:{identity_digest}"),
        # Without link_canonical a discovery has no path to a reviewer at
        # all - it would sit at processing_state="normalized" forever.
        ("link_canonical", f"link:{discovery.discovery_id}"),
    ):
        job_payload: dict[str, Any] = {"discovery_id": str(discovery.discovery_id)}
        db.add(ProcessingJob(kind=kind, dedupe_key=dedupe_key, payload=job_payload))
        pending.append(_PendingJob(kind, dedupe_key, job_payload))

    return CandidateResult(
        title=candidate.title, discovery_id=discovery.discovery_id, status="created"
    )


async def record_evidence(
    db: AsyncSession, discovery_id: uuid.UUID, payload: EvidenceSubmissionRequest
) -> tuple[int, int]:
    """Store claim-level evidence. Returns (recorded, duplicates).

    `ON CONFLICT DO NOTHING` against the uniqueness key rather than a
    check-then-insert: submission is an at-least-once path, and a resubmitted
    run must not double its own evidence.
    """
    rows = [
        {
            "discovery_id": discovery_id,
            "claim_path": item.claim_path,
            "value": item.value,
            "source_url": str(item.source_url),
            "source_type": item.source_type,
            "excerpt": item.excerpt,
            "observed_at": item.observed_at,
            "fetch_method": item.fetch_method,
            "confidence": item.confidence,
            "workflow_run_id": payload.workflow_run_id,
            "workflow_version": payload.workflow_version,
            "prompt_version": payload.prompt_version,
            "model": payload.model,
        }
        for item in payload.evidence
    ]
    inserted = await db.execute(
        insert(DiscoveryEvidence)
        .values(rows)
        .on_conflict_do_nothing(constraint="uq_discovery_evidence_claim")
        .returning(DiscoveryEvidence.evidence_id)
    )
    recorded = len(inserted.scalars().all())
    await db.commit()
    return recorded, len(rows) - recorded


async def request_review(
    db: AsyncSession, discovery_id: uuid.UUID, *, reason: str, priority: int
) -> tuple[uuid.UUID | None, bool]:
    """Open a review task for a discovery, once. Returns (id, created).

    Mirrors `infra/linking._add_review_task_once` exactly, including letting
    `uq_review_tasks_open_per_discovery` arbitrate rather than checking
    first: a check-then-insert leaves a real race between the SELECT and the
    INSERT, and this is an at-least-once path.

    Deliberately does not write `draft_recommendation`. That field is
    `prepare_review`'s deterministic output; overwriting it with the Agent's
    view would merge two different provenances into one and leave a reviewer
    unable to tell which part came from where. The Agent's own proposal
    lives on `agent_runs.recommendation`.
    """
    inserted = await db.execute(
        insert(ReviewTask)
        .values(discovery_id=discovery_id, reason=reason, priority=priority)
        .on_conflict_do_nothing(
            index_elements=["discovery_id"],
            # Must match uq_review_tasks_open_per_discovery's predicate
            # exactly. A condition that merely overlaps it does not name the
            # same index, and Postgres refuses to infer a conflict target.
            index_where=text("state = 'open' AND resolution IS NULL"),
        )
        .returning(ReviewTask.review_task_id)
    )
    review_task_id = inserted.scalar_one_or_none()

    if review_task_id is None:
        # An open task already existed. The Agent asked; the product had
        # already arranged it, and re-drafting it would discard the draft a
        # reviewer may already be looking at.
        existing = await db.scalar(
            select(ReviewTask.review_task_id).where(
                ReviewTask.discovery_id == discovery_id,
                ReviewTask.state == "open",
                ReviewTask.resolution.is_(None),
            )
        )
        await db.commit()
        return existing, False

    # A task created here is that task's only route into existence, so it is
    # also the one place to draft it.
    job_payload = {"review_task_id": str(review_task_id)}
    dedupe_key = f"prepare_review:{review_task_id}"
    db.add(ProcessingJob(kind="prepare_review", dedupe_key=dedupe_key, payload=job_payload))
    await db.commit()
    await _dispatch_pending_jobs([_PendingJob("prepare_review", dedupe_key, job_payload)])
    return review_task_id, True


async def record_run(db: AsyncSession, payload: AgentRunRequest) -> AgentRun:
    """Upsert one run's outcome.

    Keyed on (discovery_id, workflow_version): re-running the same version
    updates in place, while a new version is a genuinely new row. That is
    the reprocessing path `auto_review_evaluated_at` could not offer, since
    a one-time marker cannot distinguish "already evaluated" from
    "evaluated by an older workflow".
    """
    values = {
        "discovery_id": payload.discovery_id,
        "workflow_version": payload.workflow_version,
        "agent_outcome": payload.agent_outcome,
        "prompt_version": payload.prompt_version,
        "model": payload.model,
        "recommendation": payload.recommendation,
        "correlation_id": payload.correlation_id,
    }
    statement = (
        insert(AgentRun)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_agent_runs_discovery_workflow",
            set_={
                "agent_outcome": payload.agent_outcome,
                "prompt_version": payload.prompt_version,
                "model": payload.model,
                "recommendation": payload.recommendation,
                "correlation_id": payload.correlation_id,
                "updated_at": datetime.now(UTC),
            },
        )
        .returning(AgentRun.run_id)
    )
    run_id = (await db.execute(statement)).scalar_one()
    await db.commit()
    run = await db.get(AgentRun, run_id)
    if run is None:  # pragma: no cover - the row was committed immediately above
        # Not an assert: those are stripped under -O, which would turn this
        # into a silent None flowing back to the caller as a valid run.
        raise RuntimeError(f"agent_run {run_id} disappeared immediately after upsert")
    return run
