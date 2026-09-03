"""Track feed import runs, preserve quarantined rows, and carry the feed's own dates.

The technical design's Sheet-import contract asks for three things this schema
never had: a run-level record of import health, raw rows retained even when
they cannot become a Discovery, and the feed's own Source Posted Date / Created
Date carried through as discovery/publication signals rather than application
dates.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011_import_lineage"
down_revision = "0010_countries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crawl_runs",
        sa.Column(
            "crawl_run_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuidv7_generate()"),
        ),
        sa.Column("kind", sa.String(60), nullable=False),
        sa.Column("scope", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("state", sa.String(30), nullable=False, server_default="running"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("imported_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("repeated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("changed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_crawl_runs_kind", "crawl_runs", ["kind"])

    # No FK on source_id: a quarantined row's whole reason may be that the
    # source id does not resolve, and the row must still be storable.
    op.create_table(
        "discovery_quarantine",
        sa.Column(
            "quarantine_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuidv7_generate()"),
        ),
        sa.Column(
            "crawl_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crawl_runs.crawl_run_id"),
            nullable=False,
        ),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("raw_url", sa.Text(), nullable=True),
        sa.Column("raw_title", sa.String(500), nullable=True),
        sa.Column("raw_excerpt", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_discovery_quarantine_crawl_run_id", "discovery_quarantine", ["crawl_run_id"]
    )

    op.add_column(
        "source_pages", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.add_column(
        "discoveries",
        sa.Column(
            "crawl_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crawl_runs.crawl_run_id"),
            nullable=True,
        ),
    )
    op.add_column(
        "discoveries", sa.Column("source_posted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "discoveries", sa.Column("feed_created_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "discoveries",
        sa.Column(
            "supersedes_discovery_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("discoveries.discovery_id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("discoveries", "supersedes_discovery_id")
    op.drop_column("discoveries", "feed_created_at")
    op.drop_column("discoveries", "source_posted_at")
    op.drop_column("discoveries", "crawl_run_id")
    op.drop_column("source_pages", "last_seen_at")
    op.drop_index("ix_discovery_quarantine_crawl_run_id", table_name="discovery_quarantine")
    op.drop_table("discovery_quarantine")
    op.drop_index("ix_crawl_runs_kind", table_name="crawl_runs")
    op.drop_table("crawl_runs")
