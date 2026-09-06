"""Cache table for AI Router match_explanation results, keyed by (cycle,
searcher profile) - built in from the start rather than added once repeat
AI Router spend became a problem.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017_match_explanations"
down_revision = "0016_discovery_ai_facts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "match_explanations",
        sa.Column("explanation_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "cycle_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scholarship_cycles.cycle_id"),
            nullable=False,
        ),
        sa.Column("profile_digest", sa.String(length=64), nullable=False),
        sa.Column("facts_digest", sa.String(length=64), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("cycle_id", "profile_digest"),
    )


def downgrade() -> None:
    op.drop_table("match_explanations")
