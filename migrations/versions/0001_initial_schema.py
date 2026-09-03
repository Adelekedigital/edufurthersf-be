"""Create the initial scholarship intelligence schema."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def uuid_column():
    return postgresql.UUID(as_uuid=True), {"server_default": sa.text("gen_random_uuid()")}


def upgrade() -> None:
    uuid_type, uuid_default = uuid_column()
    json_type = postgresql.JSONB()
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.create_table(
        "providers",
        sa.Column("provider_id", uuid_type, primary_key=True, **uuid_default),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("approved_domains", json_type, nullable=False, server_default="[]"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "scholarships",
        sa.Column("scholarship_id", uuid_type, primary_key=True, **uuid_default),
        sa.Column("provider_id", uuid_type, sa.ForeignKey("providers.provider_id"), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False, unique=True),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("official_home_url", sa.Text, nullable=False),
        sa.Column("lifecycle_state", sa.String(30), nullable=False, server_default="needs_review"),
        sa.Column("current_published_revision_id", uuid_type, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "scholarship_cycles",
        sa.Column("cycle_id", uuid_type, primary_key=True, **uuid_default),
        sa.Column(
            "scholarship_id",
            uuid_type,
            sa.ForeignKey("scholarships.scholarship_id"),
            nullable=False,
        ),
        sa.Column("provider_cycle_key", sa.String(255), nullable=False),
        sa.Column("applicant_segment", sa.String(255), nullable=False, server_default="default"),
        sa.Column("official_cycle_url", sa.Text, nullable=False),
        sa.Column("public_status", sa.String(40), nullable=False),
        sa.Column("status_valid_until", sa.DateTime(timezone=True)),
        sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        sa.Column("facts", json_type, nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("scholarship_id", "provider_cycle_key", "applicant_segment"),
    )
    for table, columns in {
        "scholarship_revisions": [
            sa.Column("revision_id", uuid_type, primary_key=True, **uuid_default),
            sa.Column(
                "scholarship_id",
                uuid_type,
                sa.ForeignKey("scholarships.scholarship_id"),
                nullable=False,
            ),
            sa.Column("version", sa.Integer, nullable=False),
            sa.Column("facts", json_type, nullable=False, server_default="{}"),
            sa.Column("approved_at", sa.DateTime(timezone=True)),
            sa.Column("published_at", sa.DateTime(timezone=True)),
            sa.Column("reviewer_id", uuid_type),
            sa.UniqueConstraint("scholarship_id", "version"),
        ],
        "sources": [
            sa.Column("source_id", uuid_type, primary_key=True, **uuid_default),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("source_type", sa.String(50), nullable=False),
            sa.Column("authority_grade", sa.String(1), nullable=False),
            sa.Column("approved_domains", json_type, nullable=False, server_default="[]"),
            sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        ],
        "verifications": [
            sa.Column("verification_id", uuid_type, primary_key=True, **uuid_default),
            sa.Column(
                "revision_id",
                uuid_type,
                sa.ForeignKey("scholarship_revisions.revision_id"),
                nullable=False,
            ),
            sa.Column("result", sa.String(30), nullable=False),
            sa.Column("policy_version", sa.String(50), nullable=False),
            sa.Column("next_due_at", sa.DateTime(timezone=True)),
            sa.Column("reviewer_id", uuid_type),
        ],
        "review_tasks": [
            sa.Column("review_task_id", uuid_type, primary_key=True, **uuid_default),
            sa.Column(
                "revision_id",
                uuid_type,
                sa.ForeignKey("scholarship_revisions.revision_id"),
                nullable=False,
            ),
            sa.Column("reason", sa.String(255), nullable=False),
            sa.Column("priority", sa.Integer, nullable=False, server_default="100"),
            sa.Column("state", sa.String(30), nullable=False, server_default="open"),
            sa.Column("resolution", sa.Text),
        ],
        "processing_jobs": [
            sa.Column("job_id", uuid_type, primary_key=True, **uuid_default),
            sa.Column("kind", sa.String(60), nullable=False),
            sa.Column("dedupe_key", sa.String(500), nullable=False, unique=True),
            sa.Column("state", sa.String(30), nullable=False, server_default="queued"),
            sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
            sa.Column("payload", json_type, nullable=False, server_default="{}"),
            sa.Column("last_error", sa.Text),
        ],
        "outbox_events": [
            sa.Column("event_id", uuid_type, primary_key=True, **uuid_default),
            sa.Column("event_type", sa.String(120), nullable=False),
            sa.Column("destination", sa.String(50), nullable=False),
            sa.Column("payload", json_type, nullable=False, server_default="{}"),
            sa.Column("state", sa.String(30), nullable=False, server_default="pending"),
            sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        ],
    }.items():
        common = [
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        ]
        op.create_table(table, *columns, *common)


def downgrade() -> None:
    for table in (
        "outbox_events",
        "processing_jobs",
        "review_tasks",
        "verifications",
        "sources",
        "scholarship_revisions",
        "scholarship_cycles",
        "scholarships",
        "providers",
    ):
        op.drop_table(table)
