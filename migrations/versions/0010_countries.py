"""Mirror Core's country catalogue locally.

Core owns country identity and publishes it at the unauthenticated
`/api/v1/catalog/countries`. Search must keep working while Core is down, so
the list is mirrored into this table by a scheduled job rather than fetched per
request. `is_supported_destination` is Finder's own column, driven by verified
coverage, and the sync must never overwrite it.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_countries"
down_revision = "0009_job_backoff_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "countries",
        sa.Column(
            "country_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuidv7_generate()"),
        ),
        # ISO 3166-1 alpha-2, the value every other column refers to a country by.
        sa.Column("code", sa.String(2), nullable=False, unique=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        # Core's own row id, kept for traceability only. Core states these are
        # not stable across environments, so nothing may resolve by it.
        sa.Column("core_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Finder-owned: which destinations the index actually covers. Owned
        # here because it is a coverage decision, not a fact about the country.
        sa.Column(
            "is_supported_destination",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_countries_supported_destination",
        "countries",
        ["is_supported_destination"],
        postgresql_where=sa.text("is_supported_destination"),
    )


def downgrade() -> None:
    op.drop_index("ix_countries_supported_destination", table_name="countries")
    op.drop_table("countries")
