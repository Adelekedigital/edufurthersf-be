"""Add evidence, publication support, analytics, and anonymous-session tables."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_evidence_and_operations"
down_revision = "0004_review_discovery_target"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uid = postgresql.UUID(as_uuid=True)
    js = postgresql.JSONB
    common = [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]
    op.create_table(
        "source_snapshots",
        sa.Column(
            "snapshot_id", uid, primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("page_id", uid, sa.ForeignKey("source_pages.page_id"), nullable=False),
        sa.Column(
            "fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("extractor_version", sa.String(50), nullable=False),
        sa.Column("relevant_content", js(), nullable=False, server_default="{}"),
        sa.Column("failure_classification", sa.String(50)),
    )
    op.create_table(
        "verification_evidence",
        sa.Column(
            "evidence_id", uid, primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "verification_id", uid, sa.ForeignKey("verifications.verification_id"), nullable=False
        ),
        sa.Column("claim_path", sa.String(255), nullable=False),
        sa.Column("asserted_value", js(), nullable=False, server_default="{}"),
        sa.Column("evidence_url", sa.Text, nullable=False),
        sa.Column("excerpt", sa.Text),
        sa.Column(
            "observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("reviewer_decision", sa.String(30), nullable=False),
        *common,
    )
    op.create_table(
        "consumer_receipts",
        sa.Column("receipt_id", uid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("consumer", sa.String(80), nullable=False),
        sa.Column("event_id", uid, nullable=False),
        sa.UniqueConstraint("consumer", "event_id"),
        *common,
    )
    op.create_table(
        "anonymous_sessions",
        sa.Column("session_id", uid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("pseudonymous_id", sa.String(128), nullable=False, unique=True),
        sa.Column("consent_state", sa.String(30), nullable=False, server_default="unknown"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        *common,
    )
    op.create_table(
        "searches",
        sa.Column("search_id", uid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", uid, sa.ForeignKey("anonymous_sessions.session_id")),
        sa.Column("filter_digest", sa.String(128), nullable=False),
        sa.Column("filters", js(), nullable=False, server_default="{}"),
        sa.Column(
            "evaluated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        *common,
    )
    op.create_table(
        "join_requests",
        sa.Column(
            "join_request_id", uid, primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True),
        sa.Column("core_join_intent_id", sa.String(255)),
        sa.Column("outcome", sa.String(30), nullable=False, server_default="created"),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        *common,
    )
    op.create_table(
        "audit_log",
        sa.Column("audit_id", uid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_id", uid),
        sa.Column("reason", sa.Text),
        *common,
    )


def downgrade() -> None:
    for table in (
        "audit_log",
        "join_requests",
        "searches",
        "anonymous_sessions",
        "consumer_receipts",
        "verification_evidence",
        "source_snapshots",
    ):
        op.drop_table(table)
