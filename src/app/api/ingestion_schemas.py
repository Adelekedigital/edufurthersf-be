import uuid

from pydantic import BaseModel, Field, HttpUrl


class FeedRecord(BaseModel):
    source_id: uuid.UUID
    url: HttpUrl
    title: str = Field(min_length=1, max_length=500)
    excerpt: str | None = Field(default=None, max_length=5000)


class FeedImportRequest(BaseModel):
    records: list[FeedRecord] = Field(min_length=1, max_length=500)


class FeedImportResponse(BaseModel):
    accepted: int
    duplicates: int
    rejected: int
