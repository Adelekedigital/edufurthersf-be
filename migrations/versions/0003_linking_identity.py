"""Add indexes used by canonical discovery linking."""

from alembic import op

revision = "0003_linking_identity"
down_revision = "0002_discovery_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_discoveries_normalized_identity_key", "discoveries", ["normalized_identity_key"]
    )


def downgrade() -> None:
    op.drop_index("ix_discoveries_normalized_identity_key", table_name="discoveries")
