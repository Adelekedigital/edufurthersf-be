"""Link a published cycle to the source page `reverify_due` re-fetches, and
let a review task attach to a cycle directly rather than only a discovery.

Both columns start NULL for every existing row - the correct "never linked
yet" state - so this needs no backfill. `uq_review_tasks_open_per_cycle`
mirrors `uq_review_tasks_open_per_discovery` (0014_review_task_dedupe) for
the same reason: a recurring sweep must not be able to spawn duplicate open
tasks for the same cycle across two overlapping runs or a QStash redelivery.
No dedup-before-index step is needed here (unlike 0014) since no code path
has ever written `review_tasks.cycle_id` before this migration - it cannot
already hold duplicates.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0021_cycle_reverification_link"
down_revision = "0020_facts_contract_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scholarship_cycles",
        sa.Column(
            "source_page_id",
            UUID(as_uuid=True),
            sa.ForeignKey("source_pages.page_id"),
            nullable=True,
        ),
    )
    op.add_column(
        "review_tasks",
        sa.Column(
            "cycle_id",
            UUID(as_uuid=True),
            sa.ForeignKey("scholarship_cycles.cycle_id"),
            nullable=True,
        ),
    )
    op.create_index(
        "uq_review_tasks_open_per_cycle",
        "review_tasks",
        ["cycle_id"],
        unique=True,
        postgresql_where=sa.text("state = 'open' AND resolution IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_review_tasks_open_per_cycle", table_name="review_tasks")
    op.drop_column("review_tasks", "cycle_id")
    op.drop_column("scholarship_cycles", "source_page_id")
