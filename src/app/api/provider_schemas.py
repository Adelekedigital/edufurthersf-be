import uuid

from pydantic import BaseModel, Field, field_validator

from app.domain.urls import normalize_domain


class ProviderCreateRequest(BaseModel):
    """The organization responsible for an award - a university or a
    funding body - distinct from the sources (aggregators, official sites)
    that report on it."""

    name: str = Field(min_length=1, max_length=255)
    approved_domains: list[str] = Field(min_length=1, max_length=50)

    @field_validator("approved_domains")
    @classmethod
    def normalize_domains(cls, value: list[str]) -> list[str]:
        return [normalize_domain(domain) for domain in value]


class ProviderRead(BaseModel):
    provider_id: uuid.UUID
    name: str
    approved_domains: list[str]


class ProviderListResponse(BaseModel):
    data: list[ProviderRead]
