"""Track a Source's harvest reliability over time.

Nothing before this recorded whether a Parse.bot-backed Source's underlying
scraper-as-API has started failing consistently (the target site changed,
the marketplace listing broke, credentials expired) - a failed call was
only ever a single log line, easy to miss across weekly runs. A
consecutive-failure counter, reset on any success, makes a source that is
genuinely broken (every call fails, run after run) visible without having
to comb through logs for a pattern.

Backfilled 0/null for every existing row - correct either way, since no
code path wrote to these before this migration existed.
"""

import sqlalchemy as sa
from alembic import op

revision = "0027_source_harvest_health"
down_revision = "0026_research_provider_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column(
            "consecutive_harvest_failures", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.alter_column("sources", "consecutive_harvest_failures", server_default=None)
    op.add_column(
        "sources", sa.Column("last_harvest_failure_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("sources", "last_harvest_failure_at")
    op.drop_column("sources", "consecutive_harvest_failures")
