from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    qstash_expected_destination: str = ""
    qstash_url: str = "https://qstash.upstash.io"
    cursor_secret: str = "development-only-change-me"
    core_join_intent_url: str | None = None
    core_service_token: str | None = None
    core_allowed_return_url_prefix: str | None = None
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.0

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
