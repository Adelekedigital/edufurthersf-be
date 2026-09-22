"""Request and response shapes for the Agent integration surface.

Deliberately narrow. Every field here is something the Agent proposes or
needs in order to propose; nothing here lets it decide. There is no
`state`, no `resolution`, no `lifecycle_state` and no publish - those stay
behind the admin token and the existing review routes.
"""

import json
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

#: Aggregator, marketplace, blog and search results may support discovery,
#: but none of them is equivalent to the official page. Keeping the
#: distinction in the type means it survives into the evidence record.
SourceType = Literal[
    "official_page",
    "official_document",
    "aggregator",
    "marketplace",
    "blog_list",
    "search_result",
]

#: Exactly four, and AUTO_CHECK_ELIGIBLE is not a publication command - it
#: is an input to this service's existing deterministic gates.
AgentOutcome = Literal[
    "REVIEW_REQUIRED",
    "MORE_EVIDENCE_REQUIRED",
    "AUTO_CHECK_ELIGIBLE",
    "REJECT_RECOMMENDED",
]

FetchMethod = Literal["direct", "jina"]
Confidence = Literal["explicit", "inferred", "absent"]


class AgentDiscoveryRead(BaseModel):
    """A discovery, with the lineage the review queue does not carry.

    `GET /internal/admin/reviews` returns a reviewer's view - title,
    excerpt, draft. An agent needs the relationships: which page this came
    from, what it supersedes, what it duplicates, what it was split out of,
    and how far the product's own pipeline has taken it.
    """

    discovery_id: uuid.UUID
    source_page_id: uuid.UUID
    source_id: uuid.UUID
    source_name: str
    source_url: str
    #: The Source's fetch allowlist, so the Agent applies the same domain
    #: policy this service would rather than inventing its own.
    approved_domains: list[str]
    authority_grade: str | None
    raw_title: str | None
    raw_excerpt: str | None
    processing_state: str
    normalized_identity_key: str | None
    extracted_facts: dict[str, Any] | None
    ai_extracted_facts: dict[str, Any] | None
    supersedes_discovery_id: uuid.UUID | None
    duplicate_of_discovery_id: uuid.UUID | None
    split_from_discovery_id: uuid.UUID | None
    canonical_scholarship_id: uuid.UUID | None
    source_posted_at: datetime | None
    created_at: datetime


class AgentDiscoveryListResponse(BaseModel):
    items: list[AgentDiscoveryRead]
    #: Pass back as `after` to continue. Null when the page is the last one.
    #: A keyset cursor rather than an offset: the queue is being written to
    #: while it is being read, and an offset silently skips rows when
    #: earlier ones change.
    next_cursor: uuid.UUID | None


class CandidateSubmission(BaseModel):
    """One award extracted from a list or blog page.

    `url` is optional because plenty of list pages describe an award
    without linking to it. When absent the candidate is recorded against
    its parent's page, which is honest: that is genuinely where the claim
    was found.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    url: HttpUrl | None = None
    excerpt: str | None = Field(default=None, max_length=20_000)
    #: Where on the parent page this appeared - a heading, or a position.
    #: Part of the provenance a reviewer needs to find it again.
    heading: str | None = Field(default=None, max_length=500)


class CandidateSubmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_discovery_id: uuid.UUID
    workflow_version: str = Field(min_length=1, max_length=64)
    #: Bounded like the feed import is. A list page with more than 200
    #: distinct awards is far more likely to be a decomposition failure
    #: than a real page, and should be looked at rather than imported.
    candidates: list[CandidateSubmission] = Field(min_length=1, max_length=200)


class CandidateResult(BaseModel):
    title: str
    discovery_id: uuid.UUID | None
    #: "created" - a new discovery; "duplicate" - this exact candidate was
    #: already submitted, so the existing row is returned unchanged;
    #: "rejected" - unusable, with a reason, never silently dropped.
    status: Literal["created", "duplicate", "rejected"]
    reason: str | None = None


class CandidateSubmissionResponse(BaseModel):
    parent_discovery_id: uuid.UUID
    created: int
    duplicates: int
    rejected: int
    results: list[CandidateResult]


#: Serialized-size ceilings for the two free-form JSON fields. Every other
#: field here is length-bounded; without these, one request with 200 items
#: carrying a multi-megabyte `value` each is a single-shot out-of-memory,
#: and nothing upstream imposes a body limit.
MAX_EVIDENCE_VALUE_BYTES = 8_192
MAX_RECOMMENDATION_BYTES = 65_536


def _bounded_json(value: Any, limit: int, field: str) -> Any:
    if value is None:
        return value
    try:
        size = len(json.dumps(value, default=str).encode())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be JSON-serializable") from exc
    if size > limit:
        raise ValueError(f"{field} exceeds {limit} bytes when serialized")
    return value


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_path: str = Field(min_length=1, max_length=255)
    value: Any = None
    #: HttpUrl, not str: this is stored and later rendered to a reviewer, so
    #: a `javascript:` or `data:` URL here would be a stored-XSS seed.
    source_url: HttpUrl
    source_type: SourceType
    excerpt: str | None = Field(default=None, max_length=10_000)
    observed_at: datetime
    fetch_method: FetchMethod | None = None
    confidence: Confidence | None = None

    @field_validator("value")
    @classmethod
    def bound_value(cls, value: Any) -> Any:
        return _bounded_json(value, MAX_EVIDENCE_VALUE_BYTES, "value")


class EvidenceSubmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Identifies the run this evidence came from. Part of the uniqueness
    #: key, so resubmitting a run is idempotent while a genuinely new run
    #: can add its own evidence alongside.
    workflow_run_id: str = Field(min_length=1, max_length=128)
    workflow_version: str = Field(min_length=1, max_length=64)
    prompt_version: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=120)
    evidence: list[EvidenceItem] = Field(min_length=1, max_length=200)


class EvidenceSubmissionResponse(BaseModel):
    discovery_id: uuid.UUID
    recorded: int
    #: Already present from an earlier submission of the same run.
    duplicates: int


class AgentReviewRequest(BaseModel):
    """Ask for a human review task.

    Note what is absent: no `state`, no `resolution`, no decision. This can
    open a task; it cannot close one, and it cannot write the deterministic
    `draft_recommendation` that `prepare_review` produces.
    """

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=200)
    #: Lower surfaces first. Floored at the product's own default so an
    #: Agent-requested task cannot outrank one the deterministic pipeline
    #: raised - the previous `ge=1` let it tie for the front of the queue,
    #: which the docstring claimed it could not.
    priority: int | None = Field(default=None, ge=100, le=1000)


class AgentReviewResponse(BaseModel):
    discovery_id: uuid.UUID
    review_task_id: uuid.UUID
    #: False when an open task already existed. The Agent asked; the
    #: product had already arranged it.
    created: bool


class AgentRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    discovery_id: uuid.UUID
    workflow_version: str = Field(min_length=1, max_length=64)
    agent_outcome: AgentOutcome
    prompt_version: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=120)
    recommendation: dict[str, Any] | None = None
    correlation_id: str | None = Field(default=None, max_length=128)

    @field_validator("recommendation")
    @classmethod
    def bound_recommendation(cls, value: Any) -> Any:
        return _bounded_json(value, MAX_RECOMMENDATION_BYTES, "recommendation")


class AgentRunRead(BaseModel):
    run_id: uuid.UUID
    discovery_id: uuid.UUID
    workflow_version: str
    agent_outcome: AgentOutcome
    prompt_version: str | None
    model: str | None
    recommendation: dict[str, Any] | None
    correlation_id: str | None
    created_at: datetime
    updated_at: datetime
