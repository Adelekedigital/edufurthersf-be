"""Making schema drift visible without a database session of one's own.

Staging went stale for several sessions in a row here: migrations 0007-0011
were merged and never applied, and nothing surfaced that until a job crashed
on a missing column. `/ready` now reports the applied revision next to the one
this deployed code expects, so drift is a glance at a URL, not a postmortem.
"""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class MigrationStatus(TypedDict):
    applied: str | None
    expected: str | None
    up_to_date: bool | None


def code_migration_head() -> str | None:
    """The single migration head this checkout's `migrations/` directory
    resolves to, computed from the versions on disk rather than a hand
    maintained constant, so it cannot itself drift from what ships.

    Resolved against the process's working directory rather than this
    module's own location: the deployment image always runs with `migrations/`
    at its working directory root regardless of whether the package installed
    editable or as a built wheel, which `__file__` is not.
    """
    versions_dir = Path.cwd() / "migrations"
    if not versions_dir.is_dir():
        return None
    config = Config()
    config.set_main_option("script_location", str(versions_dir))
    return ScriptDirectory.from_config(config).get_current_head()


async def applied_migration_revision(db: AsyncSession) -> str | None:
    """The revision actually applied to this database, or None if it has
    never been migrated (no `alembic_version` table yet)."""
    exists = await db.scalar(text("SELECT to_regclass('public.alembic_version')"))
    if exists is None:
        return None
    return await db.scalar(text("SELECT version_num FROM alembic_version"))


async def migration_status(db: AsyncSession) -> MigrationStatus:
    """Compare what is applied against what this code expects.

    Failures computing either side are swallowed into `None`/`None` rather
    than raised: a packaging problem here is not the same failure `/ready`
    exists to report, and must not turn into a restart loop that cannot fix it.
    """
    try:
        expected = code_migration_head()
    except Exception:
        expected = None
    try:
        applied = await applied_migration_revision(db)
    except Exception:
        applied = None
    up_to_date = None if expected is None or applied is None else applied == expected
    return {"applied": applied, "expected": expected, "up_to_date": up_to_date}
