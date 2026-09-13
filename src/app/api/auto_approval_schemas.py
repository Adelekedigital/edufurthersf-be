import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class AutoApprovalAuditRead(BaseModel):
    audit_id: uuid.UUID
    scholarship_id: uuid.UUID
    cycle_id: uuid.UUID
    scholarship_name: str
    sampled: bool
    outcome: str
    #: The full corroboration/verification/sanity-check detail at decision
    #: time - what a human spot-checking this needs to see, not just a score.
    decision_snapshot: dict[str, Any]
    reviewer_notes: str | None = None
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    created_at: datetime


class AutoApprovalAuditListResponse(BaseModel):
    data: list[AutoApprovalAuditRead]
    total: int


class ResolveAutoApprovalAuditRequest(BaseModel):
    outcome: Literal["confirmed_correct", "confirmed_incorrect", "corrected"]
    reviewer_notes: str | None = Field(default=None, max_length=2000)
    resolved_by: str = Field(min_length=1, max_length=255)
