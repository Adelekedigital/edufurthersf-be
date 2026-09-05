import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class TaxonomyItem(BaseModel):
    code: str
    label: str


class TaxonomiesResponse(BaseModel):
    version: str
    #: Every country a student may state as their origin.
    countries: list[TaxonomyItem]
    #: The subset with verified coverage, which is where a search can be run.
    destinations: list[TaxonomyItem]
    degrees: list[TaxonomyItem]
    fields: list[TaxonomyItem]
    award_types: list[TaxonomyItem]


class SearchRequest(BaseModel):
    origin_country: str = Field(min_length=2, max_length=3)
    # Validated against the taxonomy rather than pinned here, so accepted
    # aliases ("phd") resolve to the canonical Core-aligned code in one place.
    program_level: str = Field(min_length=1, max_length=40)
    field: str = Field(min_length=1, max_length=100)
    target_countries: list[str] = Field(min_length=1, max_length=10)
    limit: int = Field(default=20, ge=1, le=50)
    cursor: str | None = None


class SearchResult(BaseModel):
    scholarship_id: uuid.UUID
    cycle_id: uuid.UUID
    name: str
    provider: str
    award_type: str
    status: str
    fit: Literal["confirmed", "possible"]
    official_url: str
    last_verified_at: datetime | None = None
    #: A real restriction origin_mode/field_mode cannot represent
    #: structurally (an exclude-one rule, an immigration status, a
    #: demographic restriction) - a distinct field so a frontend can render
    #: it as its own label, not lost inside generic matching/freshness
    #: caveats.
    eligibility_note: str | None = None
    caveats: list[str] = Field(default_factory=list)


class SearchMeta(BaseModel):
    search_id: uuid.UUID
    # Identifies the exact response page, so a later view or click event can be
    # tied to what was actually shown rather than to the search as a whole.
    response_id: uuid.UUID
    evaluated_at: datetime
    match_policy_version: str = "match-v1"
    taxonomy_version: str = "taxonomy-v1"
    confirmed_counts: dict[str, int]
    possible_match_count: int
    warnings: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    data: list[SearchResult]
    next_cursor: str | None = None
    meta: SearchMeta
