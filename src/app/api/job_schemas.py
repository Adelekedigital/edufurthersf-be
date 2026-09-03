import uuid

from pydantic import BaseModel, Field


class JobRequest(BaseModel):
    # Fixed QStash callback routes carry the job kind in the signed body.
    kind: str | None = None
    job_id: uuid.UUID | None = None
    dedupe_key: str = Field(min_length=1, max_length=500)
    payload: dict = Field(default_factory=dict)


class JobResponse(BaseModel):
    job_id: uuid.UUID
    state: str
    created: bool
