from app.core.config import Settings, normalize_database_url

_DEPLOYED_KWARGS = {"qstash_expected_destination": "https://finder.example/api/v1/internal/jobs"}


def test_posthog_dispatch_active_defaults_to_is_deployed() -> None:
    assert Settings(
        environment="production", posthog_dispatch_enabled=None, **_DEPLOYED_KWARGS
    ).posthog_dispatch_active
    assert not Settings(
        environment="development", posthog_dispatch_enabled=None
    ).posthog_dispatch_active


def test_posthog_dispatch_active_explicit_override_wins() -> None:
    assert not Settings(
        environment="production", posthog_dispatch_enabled=False, **_DEPLOYED_KWARGS
    ).posthog_dispatch_active
    assert Settings(
        environment="development", posthog_dispatch_enabled=True
    ).posthog_dispatch_active


def test_normalize_database_url_uses_asyncpg_for_generic_postgres_urls() -> None:
    assert normalize_database_url("postgres://user:pass@db/app").startswith("postgresql+asyncpg://")
    assert normalize_database_url("postgresql://user:pass@db/app").startswith(
        "postgresql+asyncpg://"
    )


def test_normalize_database_url_preserves_asyncpg_urls() -> None:
    value = "postgresql+asyncpg://user:pass@db/app"
    assert normalize_database_url(value) == value
