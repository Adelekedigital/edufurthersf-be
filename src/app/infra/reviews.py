import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.review_schemas import ReviewDecisionRequest
from app.domain.models import Discovery, ReviewTask, Scholarship
from app.domain.taxonomy import TAXONOMY


async def decide_review(
    db: AsyncSession, review_task_id: uuid.UUID, request: ReviewDecisionRequest
) -> uuid.UUID | None:
    task = await db.scalar(
        select(ReviewTask).where(ReviewTask.review_task_id == review_task_id).with_for_update()
    )
    if task is None or task.state != "open":
        raise LookupError("Open review task not found")
    scholarship_id = None
    if request.decision == "approve":
        if (
            task.discovery_id is None
            or request.provider_id is None
            or request.official_home_url is None
            or request.slug is None
            or request.award_type is None
        ):
            raise ValueError(
                "Approval requires discovery, provider, slug, award type, and official URL"
            )
        award_type = TAXONOMY.award_type(request.award_type)
        discovery = await db.scalar(
            select(Discovery).where(Discovery.discovery_id == task.discovery_id).with_for_update()
        )
        if discovery is None:
            raise LookupError("Discovery not found")
        scholarship = Scholarship(
            provider_id=request.provider_id,
            slug=request.slug,
            name=request.canonical_name or discovery.raw_title or "Unnamed scholarship",
            official_home_url=str(request.official_home_url),
            award_type=award_type,
            lifecycle_state="needs_review",
        )
        db.add(scholarship)
        await db.flush()
        discovery.canonical_scholarship_id = scholarship.scholarship_id
        discovery.processing_state = "linked"
        scholarship_id = scholarship.scholarship_id
    task.state = "resolved"
    task.resolution = request.reason[:2000]
    await db.commit()
    return scholarship_id
