import logging
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
    # Core's public API root; its reference catalogues are unauthenticated.
    core_base_url: str | None = None
    core_join_intent_url: str | None = None
    core_service_token: str | None = None
    core_allowed_return_url_prefix: str | None = None
    # The shared AI Router (LiteLLM + Langfuse) - a platform capability owned
    # outside both Core and Finder. Auth is a short-lived RS256 JWT Finder
    # signs in-process (docs/integration-scholarship-finder.md on the router
    # side) - never a static bearer token, so this is a keypair, not a
    # secret string handed to us. `ai_router_key_id` is the registered `kid`;
    # bump it (and re-register) on every rotation, never reuse one.
    ai_router_base_url: str | None = None
    ai_router_private_key_pem: str | None = None
    ai_router_key_id: str | None = None
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.0

    @field_validator("database_url")
    @classmethod
    def use_async_database_driver(cls, value: str) -> str:
        return normalize_database_url(value)

    @model_validator(mode="after")
    def require_deployed_secrets(self) -> Settings:
        """Refuse to boot a deployed environment without its signing inputs.

        Only QSTASH_EXPECTED_DESTINATION is fatal. Without it the job route
        falls back to a URL rebuilt from proxy headers, which reduces the
        signature's destination binding to a path comparison and lets a
        delivery signed for one environment be replayed against another.

        The cursor key is a warning instead. Today a forged cursor only sets an
        integer offset into results the caller can already fetch, so refusing to
        boot over it costs more than it protects. Promote this to an error when
        the cursor starts carrying ranking state, as the technical design
        intends: at that point a forged cursor reorders someone else's results.
        """
        if self.environment.lower() in DEPLOYED_ENVIRONMENTS:
            if not self.qstash_expected_destination:
                raise ValueError("QSTASH_EXPECTED_DESTINATION must be set outside development")
            if self.cursor_secret == DEVELOPMENT_CURSOR_PLACEHOLDER:
                logging.getLogger("app.config").warning(
                    "cursor_secret_is_the_development_placeholder",
                    extra={"reason": "set CURSOR_SECRET to a unique random value"},
                )
        return self

    @property
    def is_deployed(self) -> bool:
        return self.environment.lower() in DEPLOYED_ENVIRONMENTS

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
