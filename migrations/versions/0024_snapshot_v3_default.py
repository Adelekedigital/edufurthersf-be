"""Use snapshot-v3 for new result snapshots containing canonical fields."""

from alembic import op

revision = "0024_snapshot_v3_default"
down_revision = "0023_taxonomy_v3_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("searches", "snapshot_schema_version", server_default="snapshot-v3")


def downgrade() -> None:
    op.alter_column("searches", "snapshot_schema_version", server_default="snapshot-v2")
