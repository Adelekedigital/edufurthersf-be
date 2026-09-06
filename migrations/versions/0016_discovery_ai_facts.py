"""Give extract_candidate somewhere to attach an optional AI Router pass.

Separate from `extracted_facts` (the deterministic regex heuristic) rather
than merged into it: different provenance, and the router "cannot set
published or verified state" - conflating the two fields would make it look
more authoritative than a regex match, when it is exactly as provisional.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016_discovery_ai_facts"
down_revision = "0015_review_draft"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "discoveries",
        sa.Column("ai_extracted_facts", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("discoveries", "ai_extracted_facts")
