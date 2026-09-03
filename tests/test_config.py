from app.core.config import normalize_database_url


def test_normalize_database_url_uses_asyncpg_for_generic_postgres_urls() -> None:
    assert normalize_database_url("postgres://user:pass@db/app").startswith("postgresql+asyncpg://")
    assert normalize_database_url("postgresql://user:pass@db/app").startswith(
        "postgresql+asyncpg://"
    )


def test_normalize_database_url_preserves_asyncpg_urls() -> None:
    value = "postgresql+asyncpg://user:pass@db/app"
    assert normalize_database_url(value) == value
