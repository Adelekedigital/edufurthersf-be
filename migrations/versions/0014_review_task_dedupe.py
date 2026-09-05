"""Stop a discovery from ever holding more than one live review task.

Concurrent job delivery - two overlapping run-due sweeps, or QStash
redelivery racing a manual one - could each pass the application's
check-then-insert guard before either had committed, spawning duplicate
open, unresolved ReviewTask rows for the same discovery. Real incident: a
604-discovery import batch produced 1,247 excess rows this way. This
migration removes the excess before the partial unique index is added, since
the index cannot be created while duplicates already violate it.
"""

import sqlalchemy as sa
from alembic import op

revision = "0014_review_task_dedupe"
down_revision = "0013_award_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            DELETE FROM review_tasks
            WHERE review_task_id IN (
                SELECT review_task_id FROM (
                    SELECT
                        review_task_id,
                        row_number() OVER (
                            PARTITION BY discovery_id
                            ORDER BY created_at, review_task_id
                        ) AS rn
                    FROM review_tasks
                    WHERE state = 'open' AND resolution IS NULL
                ) ranked
                WHERE rn > 1
            )
            """
        )
    )
    op.create_index(
        "uq_review_tasks_open_per_discovery",
        "review_tasks",
        ["discovery_id"],
        unique=True,
        postgresql_where=sa.text("state = 'open' AND resolution IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_review_tasks_open_per_discovery", table_name="review_tasks")
