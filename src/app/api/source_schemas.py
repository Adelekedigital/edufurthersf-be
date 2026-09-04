import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.domain.urls import normalize_domain


class SourceCreateRequest(BaseModel):
    """A source the crawler is allowed to read: the curated bucket list, the
    ScholarshipRegion feed, or an approved official-site connector."""

    name: str = Field(min_length=1, max_length=255)
    source_type: str = Field(min_length=1, max_length=50)
    #: A-D authority scope, per the data verification standard.
    authority_grade: Literal["A", "B", "C", "D"]
    approved_domains: list[str] = Field(min_length=1, max_length=50)
    active: bool = True

    @field_validator("approved_domains")
    @classmethod
    def normalize_domains(cls, value: list[str]) -> list[str]:
        return [normalize_domain(domain) for domain in value]


class SourceRead(BaseModel):
    source_id: uuid.UUID
    name: str
    source_type: str
    authority_grade: str
    approved_domains: list[str]
    active: bool


class SourceListResponse(BaseModel):
    data: list[SourceRead]
