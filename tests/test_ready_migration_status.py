"""/ready reports schema drift instead of leaving it to be discovered by a crash."""

from __future__ import annotations

from sqlalchemy import text

from app.infra.migration_status import code_migration_head, migration_status
from tests.conftest import requires_db

pytestmark = requires_db


async def test_ready_reports_the_applied_and_expected_revision(client) -> None:
    response = await client.get("/ready")
    assert response.status_code == 200
    migration = response.json()["migration"]
    assert migration["expected"] == code_migration_head()
    assert migration["up_to_date"] is True
    assert migration["applied"] == migration["expected"]


async def test_readiness_status_is_unaffected_by_migration_drift(db, client) -> None:
    """A schema behind head is still an answering database; 503 stays reserved
    for connectivity failure, since a restart cannot fix a missing migration."""
    await db.execute(text("UPDATE alembic_version SET version_num = '0009_job_backoff_outbox'"))
    await db.commit()
    try:
        response = await client.get("/ready")
        assert response.status_code == 200
        assert response.json()["migration"]["up_to_date"] is False
    finally:
        await db.execute(
            text(f"UPDATE alembic_version SET version_num = '{code_migration_head()}'")
        )
        await db.commit()


async def test_a_database_never_migrated_reports_unknown_rather_than_a_false_positive(db) -> None:
    await db.execute(text("ALTER TABLE alembic_version RENAME TO alembic_version_hidden"))
    await db.commit()
    try:
        status = await migration_status(db)
        assert status == {"applied": None, "expected": code_migration_head(), "up_to_date": None}
    finally:
        await db.execute(text("ALTER TABLE alembic_version_hidden RENAME TO alembic_version"))
        await db.commit()
