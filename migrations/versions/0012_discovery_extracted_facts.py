"""Store deterministic structured-fact extraction alongside a discovery.

The target workflow's AI-extraction step has never had anywhere to write its
output: a discovery only ever carried its raw title/excerpt. This is
provisional, reviewer-facing scaffolding - a funding figure or deadline
phrase the extractor found - never a verified fact, hence nullable and
separate from anything a reviewer or publish decision touches.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012_discovery_extracted_facts"
down_revision = "0011_import_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "discoveries",
        sa.Column("extracted_facts", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("discoveries", "extracted_facts")
