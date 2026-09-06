import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ScholarshipDetailResponse(BaseModel):
    scholarship_id: uuid.UUID
    cycle_id: uuid.UUID
    name: str
    provider: str
    award_type: str
    status: str
    #: See `SearchResult.status_detail` - the same display-only refinement.
    status_detail: str
    status_valid_until: datetime | None
    official_url: str
    facts: dict = Field(default_factory=dict)
    last_verified_at: datetime | None
    #: A real restriction origin_mode/field_mode cannot represent
    #: structurally - a distinct field so a frontend can render it as its
    #: own label, not lost inside generic matching/freshness caveats.
    eligibility_note: str | None = None
    #: See `SearchResult.field_names` - the source's own course/subject
    #: wording, alongside the normalised `facts["fields"]` codes.
    field_names: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
