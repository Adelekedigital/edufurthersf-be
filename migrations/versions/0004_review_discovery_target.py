"""Allow review tasks to target unlinked discoveries."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_review_discovery_target"
down_revision = "0003_linking_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "review_tasks", "revision_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True
    )
    op.add_column(
        "review_tasks", sa.Column("discovery_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_review_tasks_discovery",
        "review_tasks",
        "discoveries",
        ["discovery_id"],
        ["discovery_id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_review_tasks_discovery", "review_tasks", type_="foreignkey")
    op.drop_column("review_tasks", "discovery_id")
    op.alter_column(
        "review_tasks", "revision_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False
    )
