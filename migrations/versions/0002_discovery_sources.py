"""Add source and discovery intake tables."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_discovery_sources"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uid = postgresql.UUID(as_uuid=True)
    common = [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]
    op.create_table(
        "source_pages",
        sa.Column("page_id", uid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_id", uid, sa.ForeignKey("sources.source_id"), nullable=False),
        sa.Column("normalized_url", sa.Text, nullable=False),
        sa.Column("normalized_content_hash", sa.String(128)),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True)),
        sa.Column("last_successful_fetch_at", sa.DateTime(timezone=True)),
        sa.Column("http_status", sa.Integer),
        sa.Column("final_url", sa.Text),
        sa.UniqueConstraint("source_id", "normalized_url"),
        *common,
    )
    op.create_table(
        "discoveries",
        sa.Column(
            "discovery_id", uid, primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("source_page_id", uid, sa.ForeignKey("source_pages.page_id"), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("raw_title", sa.String(500)),
        sa.Column("raw_excerpt", sa.Text),
        sa.Column("processing_state", sa.String(40), nullable=False, server_default="discovered"),
        sa.Column("normalized_identity_key", sa.String(500)),
        sa.Column("canonical_scholarship_id", uid),
        sa.Column("rejection_reason", sa.Text),
        sa.UniqueConstraint("source_page_id", "content_hash"),
        *common,
    )


def downgrade() -> None:
    op.drop_table("discoveries")
    op.drop_table("source_pages")
