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
    #: Without this a reviewer cannot verify anything, or tell two similarly
    #: titled candidates apart.
    raw_excerpt: str | None = None
    source_url: str | None = None
    #: Deterministic, provisional facts a heuristic extractor found - a
    #: reviewer head start, never a verified fact. Null until extract_candidate
    #: has run for this discovery.
    extracted_facts: dict | None = None
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


class PublishCycleRequest(BaseModel):
    """One application cycle's facts, in the shape search actually matches on.

    Structured fields rather than a raw dict: a published record can only
    assert destinations, levels and fields the matcher recognises, and
    ``origin_mode``/``field_mode`` gate whether ``origins``/``fields`` may be
    empty, so both are validated here rather than trusted from the caller.
    """

    provider_cycle_key: str = Field(min_length=1, max_length=255)
    applicant_segment: str = Field(default="default", max_length=255)
    official_cycle_url: HttpUrl
    public_status: Literal["open_verified", "expected_to_reopen", "status_unknown"]
    status_valid_until: datetime | None = None
    last_verified_at: datetime | None = None

    #: Countries this cycle admits study in. Limited to verified destination
    #: coverage, unlike ``origins`` below.
    destinations: list[str] = Field(min_length=1, max_length=20)
    #: Degree levels this cycle accepts, e.g. "masters", "doctorate".
    levels: list[str] = Field(min_length=1, max_length=10)
    origin_mode: Literal["restricted", "unrestricted", "unknown"] = "unknown"
    origins: list[str] = Field(default_factory=list, max_length=250)
    field_mode: Literal["restricted", "all", "unknown"] = "unknown"
    fields: list[str] = Field(default_factory=list, max_length=50)
    #: Whether the evidence behind this cycle is current, per the reviewer's
    #: own judgement — not derived from anything else in this request.
    evidence_fresh: bool = False
    #: The application deadline, if the provider has stated one. A discovery
    #: signal a reviewer verified, never invented.
    deadline_at: datetime | None = None
    #: Whether `deadline_at` is a calendar date or a precise instant. Most
    #: real provider deadlines are dates, not times, hence the default - a
    #: date-only deadline gets no invented time of day or countdown.
    deadline_precision: Literal["date", "datetime"] = "date"
    #: The provider's own IANA timezone, if known (e.g. "America/New_York").
    #: Left unset when precision is "date" and the timezone is not known: the
    #: cutoff then fails closed to the earliest place on Earth the date ends,
    #: rather than assuming a viewer's or a server's timezone.
    deadline_timezone: str | None = None


class PublishCycleResponse(BaseModel):
    scholarship_id: uuid.UUID
    cycle_id: uuid.UUID
    lifecycle_state: str
    public_status: str


class RunDueJobsResponse(BaseModel):
    completed: int
    failed: int
    #: Still due after this call - a real count past the request's limit,
    #: not a hint that anything was skipped incorrectly.
    remaining: int
