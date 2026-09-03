import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Discovery
from app.domain.normalization import normalize_discovery
from app.infra.jobs import claim_job_for_execution, complete_job, fail_job_for_execution
from app.infra.linking import link_discovery
from app.infra.source_persistence import fetch_and_persist_page


async def execute_job(db: AsyncSession, job_id: uuid.UUID) -> str:
    """Claim and execute one durable job; callers can safely retry delivery."""
    job = await claim_job_for_execution(db, job_id)
    try:
        if job.kind == "normalize_discovery":
            await _normalize_discovery(db, job.payload)
        elif job.kind == "link_canonical":
            await link_discovery(db, uuid.UUID(job.payload["discovery_id"]))
        elif job.kind == "fetch_source_page":
            await fetch_and_persist_page(db, uuid.UUID(job.payload["page_id"]))
        else:
            # Unimplemented kinds remain durable and visible rather than being
            # acknowledged as successful no-ops.
            raise ValueError(f"No worker handler for {job.kind}")
        await complete_job(db, job)
        return job.state
    except Exception as exc:
        await fail_job_for_execution(db, job, str(exc))
        raise


async def _normalize_discovery(db: AsyncSession, payload: dict) -> None:
    discovery = await db.scalar(
        select(Discovery)
        .where(Discovery.discovery_id == uuid.UUID(payload["discovery_id"]))
        .with_for_update()
    )
    if discovery is None:
        raise LookupError("Discovery not found")
    normalized = normalize_discovery(discovery.raw_title or "")
    discovery.normalized_identity_key = normalized.identity_key
    discovery.processing_state = "normalized"
    await db.commit()
