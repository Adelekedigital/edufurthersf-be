"""Persist a real fetch of a discovery's own page, for human audit.

Nothing before this ever kept the actual text of a fetched page -
SourceSnapshot only stores a content hash and byte length, by design (its job
is change detection, not evidence retention). Auto-approving a candidate on
real-page verification needs the opposite: a durable record of what the AI
actually saw, so a human spot-checking an auto-approval later doesn't have to
take the decision's word for it.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0028_discovery_verifications"
down_revision = "0027_source_harvest_health"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discovery_verifications",
        sa.Column(
            "verification_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            "discovery_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("discoveries.discovery_id"),
            nullable=False,
        ),
        sa.Column("fetched_url", sa.Text(), nullable=False),
        sa.Column("fetch_method", sa.String(length=20), nullable=False),
        sa.Column("page_text", sa.Text(), nullable=False),
        sa.Column("ai_reextracted_facts", postgresql.JSONB(), nullable=True),
        sa.Column("agreement", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_discovery_verifications_discovery_id",
        "discovery_verifications",
        ["discovery_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_discovery_verifications_discovery_id", table_name="discovery_verifications")
    op.drop_table("discovery_verifications")
