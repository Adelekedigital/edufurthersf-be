import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class ReviewDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    provider_id: uuid.UUID | None = None
    canonical_name: str | None = Field(default=None, min_length=1, max_length=500)
    official_home_url: HttpUrl | None = None
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    reason: str = Field(min_length=1, max_length=2000)


class ReviewDecisionResponse(BaseModel):
    review_task_id: uuid.UUID
    decision: str
    scholarship_id: uuid.UUID | None = None


class ReviewTaskSummary(BaseModel):
    review_task_id: uuid.UUID
    reason: str
    priority: int
    state: str
    discovery_id: uuid.UUID | None = None
    revision_id: uuid.UUID | None = None
    raw_title: str | None = None
    created_at: datetime


class ReviewQueueResponse(BaseModel):
    data: list[ReviewTaskSummary]
    open_count: int


class WithdrawRequest(BaseModel):
    # A withdrawal removes a record from public results, so the reason is the
    # audit trail for why it stopped being publishable.
    reason: str = Field(min_length=1, max_length=2000)


class WithdrawResponse(BaseModel):
    scholarship_id: uuid.UUID
    lifecycle_state: str
    withdrawn_cycles: int
