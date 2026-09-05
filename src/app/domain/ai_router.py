"""The domain port for the shared Edufurther AI Router.

Per the Analytics & Metrics Standard §5: model routing and provider fallback
(LiteLLM + Langfuse) is a shared platform capability, independent of both
Core and Finder - "rather than building those platforms in the Finder
sprint." This repo owns the port and the infra adapter that calls it, never
the router itself, and never a vendor SDK directly (that boundary is
mechanically enforced the same way domain/ has no FastAPI or SQLAlchemy
imports).

A task returns candidate structured data for downstream review, same as
extract_candidate and prepare_review already do without an LLM: "the router
has no access to Core identity/payment databases" and "cannot set published
or verified state." Nothing behind this port may ever be treated as an
executed decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class AITask(StrEnum):
    """The standard's allowlisted task names - default deny, not an open enum."""

    scholarship_extraction = "scholarship_extraction"
    match_explanation = "match_explanation"


#: The standard's proposed initial extraction timeout, end-to-end.
DEFAULT_TIMEOUT_SECONDS = 45
#: The standard's cap: "maximum two provider attempts."
MAX_PROVIDER_ATTEMPTS = 2


@dataclass(frozen=True)
class AIRouterRequest:
    """One task request, shaped to the router's documented contract.

    `source_data` is a bounded excerpt only - never secrets, never raw source
    HTML, never a user's sensitive data: "allowlisted jobs send only relevant
    source excerpts." Model IDs and provider keys are router-side policy, not
    a caller's concern - this request never names one.
    """

    task: AITask
    task_version: str
    schema_version: int
    product_id: str
    feature_id: str
    correlation_id: str
    idempotency_key: str
    source_data: dict[str, Any]
    journey_id: str | None = None
    session_id: str | None = None
    handoff_id: str | None = None


class AIRouterOutcome(StrEnum):
    completed = "completed"
    invalid_schema = "invalid_schema"
    budget_exhausted = "budget_exhausted"
    provider_unavailable = "provider_unavailable"


@dataclass(frozen=True)
class AIRouterResponse:
    """Schema-validated output for a human/downstream process to review.

    Never a verdict this port can act on unsupervised - `output` is exactly
    as provisional as extract_candidate's own extraction, just from a model
    instead of a regex.
    """

    request_id: str
    outcome: AIRouterOutcome
    output: dict[str, Any] | None
    model_policy_version: str | None
    trace_reference: str | None


class AIRouterPort(Protocol):
    """What a future extract_candidate/prepare_review upgrade calls.

    Implemented in infra by an adapter against the shared router - never a
    vendor SDK called directly from domain or application code. No adapter
    exists to call yet: this port has nothing behind it in production until
    the router itself is provisioned as its own service.
    """

    async def execute(self, request: AIRouterRequest) -> AIRouterResponse: ...
