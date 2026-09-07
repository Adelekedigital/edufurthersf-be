"""Catch up searches' version-column server defaults to v2.

0018 bumped the Python-side ORM default= for these three columns
(snapshot_schema_version/match_policy_version/taxonomy_version) but missed
the Postgres-level server_default set when the table was created (0008) -
the two are separate mechanisms and only the DB-level one actually applies
to a row inserted by anything that bypasses the ORM (a raw SQL insert, a
future backfill/admin script). The one production write path
(record_search_response) always sets all three explicitly, so this was
inert today, not a live bug - closing it before it becomes one.
"""

import sqlalchemy as sa
from alembic import op

revision = "0019_search_version_defaults_v2"
down_revision = "0018_provider_country"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("searches", "snapshot_schema_version", server_default="snapshot-v2")
    op.alter_column("searches", "match_policy_version", server_default="match-v2")
    op.alter_column("searches", "taxonomy_version", server_default="taxonomy-v2")


def downgrade() -> None:
    op.alter_column("searches", "snapshot_schema_version", server_default="snapshot-v1")
    op.alter_column("searches", "match_policy_version", server_default="match-v1")
    op.alter_column("searches", "taxonomy_version", server_default="taxonomy-v1")
