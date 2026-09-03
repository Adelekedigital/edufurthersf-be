from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(value: str) -> str:
    """Use the asyncpg driver even when a host supplies a generic Postgres URL."""
    if value.startswith("postgres://"):
        return "postgresql+asyncpg://" + value.removeprefix("postgres://")
    if value.startswith("postgresql://"):
        return "postgresql+asyncpg://" + value.removeprefix("postgresql://")
    if value.startswith("postgresql+psycopg2://"):
        return "postgresql+asyncpg://" + value.removeprefix("postgresql+psycopg2://")
    return value


class Settings(BaseSettings):
    app_name: str = "scholarship-finder"
    app_version: str = "0.1.0"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/scholarship_finder"
    db_connect_timeout_seconds: float = 3.0
    api_rate_limit_per_minute: int = 30
    internal_service_token: str | None = None
    qstash_current_signing_key: str | None = None
    qstash_next_signing_key: str | None = None
    qstash_token: str | None = None
    qstash_expected_destination: str = ""
    qstash_url: str = "https://qstash.upstash.io"
    cursor_secret: str = "development-only-change-me"
    core_join_intent_url: str | None = None
    core_service_token: str | None = None
    core_allowed_return_url_prefix: str | None = None
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.0

    @field_validator("database_url")
    @classmethod
    def use_async_database_driver(cls, value: str) -> str:
        return normalize_database_url(value)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
