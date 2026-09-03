import uuid

from pydantic import BaseModel, Field, HttpUrl


class JoinIntentRequest(BaseModel):
    search_id: uuid.UUID
    consent: bool
    return_url: HttpUrl
    idempotency_key: str = Field(min_length=16, max_length=255)


class JoinIntentResponse(BaseModel):
    status: str
    continue_url: HttpUrl | None = None
    handoff_token: str | None = None
