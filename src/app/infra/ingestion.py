import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ingestion_schemas import FeedRecord
from app.core.config import get_settings
from app.domain.ingestion import prepare_candidate
from app.domain.models import (
    CrawlRun,
    Discovery,
    DiscoveryQuarantine,
    ProcessingJob,
    Source,
    SourcePage,
)
from app.domain.normalization import normalize_discovery
from app.infra.qstash import QStashPublisher

logger = logging.getLogger("app.infra.ingestion")


@dataclass(frozen=True)
class ImportOutcome:
    crawl_run_id: uuid.UUID
    imported: int
    repeated: int
    changed: int
    rejected: int


@dataclass(frozen=True)
class _PendingJob:
    kind: str
    dedupe_key: str
    payload: dict[str, Any]


async def _quarantine(
    db: AsyncSession,
    crawl_run: CrawlRun,
    record: FeedRecord,
    *,
    raw_url: str | None,
    reason: str,
) -> None:
    """Preserve a row that could not become a Discovery.

    Never silently dropped: "quarantine unparsable rows" only means something
    if the raw row survives it, which is why this exists as a table rather than
    a counter.
    """
    db.add(
        DiscoveryQuarantine(
            crawl_run_id=crawl_run.crawl_run_id,
            source_id=record.source_id,
            raw_url=raw_url,
            raw_title=record.title,
            raw_excerpt=record.excerpt,
            reason=reason,
        )
    )


async def _dispatch_pending_jobs(pending: list[_PendingJob]) -> None:
    """Publish each freshly committed job to QStash so `/internal/jobs`
    actually executes it, instead of leaving it at `state=queued` until
    someone calls the manual `run-due` stopgap.

    Only ever called after the caller's own commit has already succeeded:
    publishing before that would risk QStash delivering a callback for a
    ProcessingJob - and the Discovery its payload references - that a
    rollback made never exist.

    Best-effort per job: QStash being briefly unreachable must not turn a
    successful import into a failed one. The local ProcessingJob row still
    exists either way, so `run-due` remains the safety net for anything that
    does not get dispatched here.
    """
    settings = get_settings()
    if not settings.qstash_token or not settings.qstash_expected_destination:
        # Local/test environments without QStash configured fall back to the
        # manual run-due stopgap entirely - expected, not an error.
        return
    publisher = QStashPublisher(settings.qstash_url, settings.qstash_token)

    async def _publish_one(job: _PendingJob) -> None:
        try:
            await publisher.publish(
                settings.qstash_expected_destination,
                {"kind": job.kind, "dedupe_key": job.dedupe_key, "payload": job.payload},
                deduplication_id=job.dedupe_key,
            )
        except Exception:
            logger.warning("qstash_dispatch_failed", extra={"job_kind": job.kind})

    await asyncio.gather(*(_publish_one(job) for job in pending))


async def import_feed_records(db: AsyncSession, records: list[FeedRecord]) -> ImportOutcome:
    """Import one batch of feed rows under a single crawl run.

    Every row lands in exactly one of four buckets: ``imported`` (a URL never
    seen before), ``repeated`` (an already known URL, unchanged), ``changed``
    (an already known URL whose content moved, so a new revision is created
    without discarding the old one), or ``rejected`` (quarantined, not
    dropped). Repeated URLs always update ``last_seen_at`` on their page,
    independent of which bucket they land in.
    """
    crawl_run = CrawlRun(
        kind="import_feed",
        scope={
            "record_count": len(records),
            "source_ids": sorted({str(record.source_id) for record in records}),
        },
    )
    db.add(crawl_run)
    await db.flush()

    imported = repeated = changed = rejected = 0
    pending_jobs: list[_PendingJob] = []
    try:
        for record in records:
            try:
                candidate = prepare_candidate(str(record.url), record.title, record.excerpt)
            except ValueError:
                await _quarantine(
                    db, crawl_run, record, raw_url=str(record.url), reason="invalid_url"
                )
                rejected += 1
                continue

            source = await db.scalar(
                select(Source).where(Source.source_id == record.source_id, Source.active.is_(True))
            )
            if source is None:
                await _quarantine(
                    db,
                    crawl_run,
                    record,
                    raw_url=candidate.normalized_url,
                    reason="unknown_or_inactive_source",
                )
                rejected += 1
                continue

            now = datetime.now(UTC)
            page = await db.scalar(
                select(SourcePage).where(
                    SourcePage.source_id == source.source_id,
                    SourcePage.normalized_url == candidate.normalized_url,
                )
            )
            if page is None:
                page = SourcePage(
                    source_id=source.source_id,
                    normalized_url=candidate.normalized_url,
                    last_seen_at=now,
                )
                db.add(page)
                await db.flush()
            else:
                page.last_seen_at = now

            existing = await db.scalar(
                select(Discovery).where(
                    Discovery.source_page_id == page.page_id,
                    Discovery.content_hash == candidate.content_hash,
                )
            )
            if existing is not None:
                repeated += 1
                continue

            head = await db.scalar(
                select(Discovery)
                .where(Discovery.source_page_id == page.page_id)
                .order_by(Discovery.created_at.desc())
                .limit(1)
            )
            normalized = normalize_discovery(candidate.title)
            discovery = Discovery(
                source_page_id=page.page_id,
                crawl_run_id=crawl_run.crawl_run_id,
                content_hash=candidate.content_hash,
                raw_title=candidate.title,
                raw_excerpt=candidate.excerpt,
                source_posted_at=record.source_posted_at,
                feed_created_at=record.feed_created_at,
                normalized_identity_key=normalized.identity_key,
                processing_state="normalized",
                supersedes_discovery_id=head.discovery_id if head is not None else None,
            )
            db.add(discovery)
            await db.flush()

            normalize_payload = {"discovery_id": str(discovery.discovery_id)}
            normalize_dedupe_key = f"normalize:{discovery.discovery_id}:{normalized.identity_key}"
            db.add(
                ProcessingJob(
                    kind="normalize_discovery",
                    dedupe_key=normalize_dedupe_key,
                    payload=normalize_payload,
                    correlation_id=str(crawl_run.crawl_run_id),
                )
            )
            pending_jobs.append(
                _PendingJob("normalize_discovery", normalize_dedupe_key, normalize_payload)
            )

            # Without this, a discovery has no path to a reviewer at all:
            # nothing else ever calls link_discovery for it, so it would sit at
            # processing_state="normalized" forever no matter how many rows
            # import. One discovery_id is only ever created once, so the key
            # needs no further disambiguation.
            link_payload = {"discovery_id": str(discovery.discovery_id)}
            link_dedupe_key = f"link:{discovery.discovery_id}"
            db.add(
                ProcessingJob(
                    kind="link_canonical",
                    dedupe_key=link_dedupe_key,
                    payload=link_payload,
                    correlation_id=str(crawl_run.crawl_run_id),
                )
            )
            pending_jobs.append(_PendingJob("link_canonical", link_dedupe_key, link_payload))

            if head is not None:
                changed += 1
            else:
                imported += 1

        crawl_run.state = "completed"
    except Exception as exc:
        crawl_run.state = "failed"
        crawl_run.last_error = str(exc)[:1000]
        raise
    finally:
        crawl_run.finished_at = datetime.now(UTC)
        crawl_run.imported_count = imported
        crawl_run.repeated_count = repeated
        crawl_run.changed_count = changed
        crawl_run.rejected_count = rejected
        await db.commit()

    # Only reachable once the commit above has actually succeeded, whether the
    # run ended completed or failed partway through - either way, whatever was
    # added to the session up to that point is now durably persisted, so any
    # jobs collected for it are safe to publish.
    if pending_jobs:
        await _dispatch_pending_jobs(pending_jobs)

    return ImportOutcome(crawl_run.crawl_run_id, imported, repeated, changed, rejected)
