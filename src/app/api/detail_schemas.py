import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ScholarshipDetailResponse(BaseModel):
    scholarship_id: uuid.UUID
    cycle_id: uuid.UUID
    name: str
    provider: str
    status: str
    status_valid_until: datetime | None
    official_url: str
    facts: dict = Field(default_factory=dict)
    last_verified_at: datetime | None
    caveats: list[str] = Field(default_factory=list)
