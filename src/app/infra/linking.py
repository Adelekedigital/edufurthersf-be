import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.linking import LinkOutcome, decide_link
from app.domain.models import Discovery, ReviewTask, Scholarship


async def link_discovery(db: AsyncSession, discovery_id: uuid.UUID) -> LinkOutcome:
    discovery = await db.scalar(
        select(Discovery).where(Discovery.discovery_id == discovery_id).with_for_update()
    )
    if discovery is None:
        raise LookupError("Discovery not found")
    candidates = await db.scalars(
        select(Scholarship.scholarship_id).where(Scholarship.name.ilike(discovery.raw_title or ""))
    )
    decision = decide_link([str(value) for value in candidates])
    if decision.outcome == LinkOutcome.linked:
        discovery.canonical_scholarship_id = uuid.UUID(decision.scholarship_id)
        discovery.processing_state = LinkOutcome.linked.value
    elif decision.outcome == LinkOutcome.needs_review:
        discovery.processing_state = LinkOutcome.needs_review.value
        db.add(ReviewTask(discovery_id=discovery.discovery_id, reason=decision.reason, priority=50))
    else:
        discovery.processing_state = LinkOutcome.new_candidate.value
    await db.commit()
    return decision.outcome
