"""Give jobs a retry schedule and a lease, and outbox events a dedupe key.

`fail_job` computed an exponential backoff and returned it, but no column held
it, so a failed job carried no due time and nothing could sweep abandoned work.
Outbox events had no idempotency key, so a retried request could record the
same business event twice.
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_job_backoff_outbox"
down_revision = "0008_search_result_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "processing_jobs", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "processing_jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("processing_jobs", sa.Column("correlation_id", sa.String(128), nullable=True))
    op.create_index("ix_processing_jobs_state", "processing_jobs", ["state"])
    op.create_index("ix_processing_jobs_next_attempt_at", "processing_jobs", ["next_attempt_at"])

    # Existing rows predate the key; the event id is unique and stable, so it
    # backfills without inventing a false business identity.
    op.add_column("outbox_events", sa.Column("dedupe_key", sa.String(500), nullable=True))
    op.execute("UPDATE outbox_events SET dedupe_key = event_id::text WHERE dedupe_key IS NULL")
    op.alter_column("outbox_events", "dedupe_key", nullable=False)
    op.create_unique_constraint("uq_outbox_events_dedupe_key", "outbox_events", ["dedupe_key"])
    op.add_column(
        "outbox_events", sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_outbox_events_destination", "outbox_events", ["destination"])
    op.create_index("ix_outbox_events_state", "outbox_events", ["state"])


def downgrade() -> None:
    op.drop_index("ix_outbox_events_state", table_name="outbox_events")
    op.drop_index("ix_outbox_events_destination", table_name="outbox_events")
    op.drop_column("outbox_events", "dispatched_at")
    op.drop_constraint("uq_outbox_events_dedupe_key", "outbox_events", type_="unique")
    op.drop_column("outbox_events", "dedupe_key")
    op.drop_index("ix_processing_jobs_next_attempt_at", table_name="processing_jobs")
    op.drop_index("ix_processing_jobs_state", table_name="processing_jobs")
    op.drop_column("processing_jobs", "correlation_id")
    op.drop_column("processing_jobs", "lease_expires_at")
    op.drop_column("processing_jobs", "next_attempt_at")
