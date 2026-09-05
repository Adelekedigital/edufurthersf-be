"""Give prepare_review somewhere to attach a drafted recommendation.

Nullable and separate from `resolution`: a draft is a proposal a human
reviewer confirms or edits, never a decision - it must not read like one, and
must not require touching a task's existing open/resolved bookkeeping to
exist.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015_review_draft"
down_revision = "0014_review_task_dedupe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "review_tasks",
        sa.Column("draft_recommendation", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("review_tasks", "draft_recommendation")
