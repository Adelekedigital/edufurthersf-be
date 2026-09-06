import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class MatchProfileRequest(BaseModel):
    """A searcher's profile against one specific, already-identified
    scholarship - no `target_countries` the way `SearchRequest` needs one,
    since the destination is already fixed by whichever scholarship this is."""

    origin_country: str = Field(min_length=2, max_length=3)
    program_level: str = Field(min_length=1, max_length=40)
    field: str | None = Field(default=None, max_length=100)


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
    #: AI Router elaboration on this searcher's deterministic match decision
    #: - only ever set by `POST` with a profile; a bare `GET` (no profile,
    #: e.g. a shared link) never triggers an AI Router call, so this stays
    #: null there. Never itself a verdict - the decision it explains was
    #: already made by `evaluate_match` before this was ever requested.
    match_explanation: str | None = None
