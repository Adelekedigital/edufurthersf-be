import uuid
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
