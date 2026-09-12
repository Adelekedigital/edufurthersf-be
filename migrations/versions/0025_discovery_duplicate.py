"""Track cross-source discovery duplicates.

Add Discovery.duplicate_of_discovery_id so link_discovery can mark a new
discovery as a duplicate of an already-pending one reported by a different
source page, instead of opening a second review task for the same real-world
award - the exact "two review_task_ids for one listing" bug
docs/candidate-verification-standard.md already documents.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0025_discovery_duplicate"
down_revision = "0024_snapshot_v3_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "discoveries",
        sa.Column(
            "duplicate_of_discovery_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("discoveries.discovery_id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("discoveries", "duplicate_of_discovery_id")
