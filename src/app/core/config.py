from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The placeholder cursor key that require_deployed_secrets refuses to boot with.
DEVELOPMENT_CURSOR_PLACEHOLDER = "development-only-change-me"
DEPLOYED_ENVIRONMENTS = frozenset({"staging", "production"})


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

    @model_validator(mode="after")
    def require_deployed_secrets(self) -> Settings:
        """Refuse to boot a deployed environment with placeholder secrets.

        Shipping the development cursor key would let anyone mint pagination
        cursors, and it is the kind of default that survives to production
        precisely because nothing complains about it.
        """
        if self.environment.lower() in DEPLOYED_ENVIRONMENTS:
            if self.cursor_secret == DEVELOPMENT_CURSOR_PLACEHOLDER:
                raise ValueError("CURSOR_SECRET must be set outside development")
            if not self.qstash_expected_destination:
                raise ValueError("QSTASH_EXPECTED_DESTINATION must be set outside development")
        return self

    @property
    def is_deployed(self) -> bool:
        return self.environment.lower() in DEPLOYED_ENVIRONMENTS

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
