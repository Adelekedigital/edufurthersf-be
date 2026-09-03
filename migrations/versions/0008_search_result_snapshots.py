"""Record what search returned, not only what was asked.

`searches` held the normalised filters and nothing else, so nothing could
explain an irrelevant result, a zero-match search, a ranking change or an
official-link click after the catalogue moved on. The table becomes one row per
evaluated response page, grouped by a logical `search_id`, carrying the public
result objects in their returned order.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_search_result_snapshots"
down_revision = "0007_enum_check_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # search_id stops being unique: page requests of one logical search share it
    # and each gets its own response row.
    op.add_column(
        "searches",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuidv7_generate()")),
    )
    op.execute("UPDATE searches SET id = search_id WHERE id IS NULL")
    op.alter_column("searches", "id", nullable=False)
    op.drop_constraint("searches_pkey", "searches", type_="primary")
    op.create_primary_key("searches_pkey", "searches", ["id"])
    op.create_index("ix_searches_search_id", "searches", ["search_id"])

    for column in (
        sa.Column(
            "result_snapshot", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column(
            "snapshot_schema_version", sa.String(20), nullable=False, server_default="snapshot-v1"
        ),
        sa.Column("match_policy_version", sa.String(50), nullable=False, server_default="match-v1"),
        sa.Column("taxonomy_version", sa.String(50), nullable=False, server_default="taxonomy-v1"),
        sa.Column("page_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("requested_limit", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("returned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_match_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    ):
        op.add_column("searches", column)

    # Expiry removes the whole row, so the sweep reads this index directly.
    op.create_index("ix_searches_expires_at", "searches", ["expires_at"])
    # A page is only meaningful once within its logical search.
    op.create_unique_constraint(
        "uq_searches_search_id_page", "searches", ["search_id", "page_number"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_searches_search_id_page", "searches", type_="unique")
    op.drop_index("ix_searches_expires_at", table_name="searches")
    for name in (
        "expires_at",
        "duration_ms",
        "total_match_count",
        "returned_count",
        "requested_limit",
        "page_number",
        "taxonomy_version",
        "match_policy_version",
        "snapshot_schema_version",
        "result_snapshot",
    ):
        op.drop_column("searches", name)
    op.drop_index("ix_searches_search_id", table_name="searches")
    op.drop_constraint("searches_pkey", "searches", type_="primary")
    op.create_primary_key("searches_pkey", "searches", ["search_id"])
    op.drop_column("searches", "id")
