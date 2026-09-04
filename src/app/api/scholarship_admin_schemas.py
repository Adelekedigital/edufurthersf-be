import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ScholarshipCycleAdminRead(BaseModel):
    cycle_id: uuid.UUID
    provider_cycle_key: str
    applicant_segment: str
    official_cycle_url: str
    #: As stored on the row - the value the last publish or sweep wrote.
    public_status: str
    #: Recomputed now, the same way search and detail do - lets a tester see a
    #: stored `open_verified` that a passed deadline has since made stale,
    #: without waiting for a sweep to catch up.
    evaluated_public_status: str
    status_valid_until: datetime | None = None
    last_verified_at: datetime | None = None
    facts: dict[str, Any]


class ScholarshipAdminRead(BaseModel):
    scholarship_id: uuid.UUID
    slug: str
    name: str
    official_home_url: str
    lifecycle_state: str
    provider_id: uuid.UUID
    provider_name: str
    cycles: list[ScholarshipCycleAdminRead]


class ScholarshipAdminListResponse(BaseModel):
    data: list[ScholarshipAdminRead]
    #: Total rows matching the filters, independent of `limit` - a real count,
    #: not capped by the page just returned.
    total: int
