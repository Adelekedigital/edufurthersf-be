"""Schema for auto-approve (Phase 2c): visible labeling + the sampling audit.

Four additions landing together as one feature, not four independent
concepts: `discoveries.auto_review_evaluated_at` (a single evaluation marker
so the sweep never re-attempts the same candidate every hour),
`scholarship_cycles.is_auto_approved`/`auto_approval_score` (the visible
distinction an auto-approved record must carry - never indistinguishable
from a reviewer-approved one), `audit_log.context` (structured detail for
the richer audit entry auto-approval writes), and `auto_approval_audits`
(the sampling-audit table closing the feedback loop
docs/candidate-verification-standard.md calls for).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0029_auto_approval_schema"
down_revision = "0028_discovery_verifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "discoveries",
        sa.Column("auto_review_evaluated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scholarship_cycles",
        sa.Column("is_auto_approved", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "scholarship_cycles", sa.Column("auto_approval_score", sa.Integer(), nullable=True)
    )
    op.add_column("audit_log", sa.Column("context", postgresql.JSONB(), nullable=True))
    op.create_table(
        "auto_approval_audits",
        sa.Column("audit_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "scholarship_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scholarships.scholarship_id"),
            nullable=False,
        ),
        sa.Column(
            "cycle_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scholarship_cycles.cycle_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "decision_snapshot", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column("sampled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("outcome", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("auto_approval_audits")
    op.drop_column("audit_log", "context")
    op.drop_column("scholarship_cycles", "auto_approval_score")
    op.drop_column("scholarship_cycles", "is_auto_approved")
    op.drop_column("discoveries", "auto_review_evaluated_at")
