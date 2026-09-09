"""Use taxonomy-v3 for newly-created search response rows.

Existing rows intentionally retain their recorded taxonomy version so retained
historical search snapshots remain explainable.
"""

from alembic import op

revision = "0023_taxonomy_v3_default"
down_revision = "0022_cycle_auto_downgraded"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("searches", "taxonomy_version", server_default="taxonomy-v3")


def downgrade() -> None:
    op.alter_column("searches", "taxonomy_version", server_default="taxonomy-v2")
