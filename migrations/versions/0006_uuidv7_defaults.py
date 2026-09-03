"""Use a UUIDv7-compatible PostgreSQL generator for new identifiers."""

from alembic import op

revision = "0006_uuidv7_defaults"
down_revision = "0005_evidence_and_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE OR REPLACE FUNCTION uuidv7_generate() RETURNS uuid
    LANGUAGE plpgsql VOLATILE AS $$
    DECLARE
        timestamp_hex text;
        random_hex text;
    BEGIN
        timestamp_hex := lpad(
            to_hex((extract(epoch from clock_timestamp()) * 1000)::bigint),
            12,
            '0'
        );
        random_hex := encode(gen_random_bytes(11), 'hex');
        RETURN (
            substr(timestamp_hex, 1, 8) || '-' || substr(timestamp_hex, 9, 4) || '-7' ||
            substr(random_hex, 1, 3) || '-8' ||
            substr(random_hex, 4, 3) || '-' || substr(random_hex, 7, 12)
        )::uuid;
    END;
    $$;
    """)
    for table, column in (
        ("providers", "provider_id"),
        ("scholarships", "scholarship_id"),
        ("scholarship_cycles", "cycle_id"),
        ("scholarship_revisions", "revision_id"),
        ("sources", "source_id"),
        ("source_pages", "page_id"),
        ("source_snapshots", "snapshot_id"),
        ("discoveries", "discovery_id"),
        ("verifications", "verification_id"),
        ("verification_evidence", "evidence_id"),
        ("review_tasks", "review_task_id"),
        ("processing_jobs", "job_id"),
        ("outbox_events", "event_id"),
        ("consumer_receipts", "receipt_id"),
        ("anonymous_sessions", "session_id"),
        ("searches", "search_id"),
        ("join_requests", "join_request_id"),
        ("audit_log", "audit_id"),
    ):
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT uuidv7_generate()")


def downgrade() -> None:
    for table, column in (
        ("providers", "provider_id"),
        ("scholarships", "scholarship_id"),
        ("scholarship_cycles", "cycle_id"),
        ("scholarship_revisions", "revision_id"),
        ("sources", "source_id"),
        ("source_pages", "page_id"),
        ("source_snapshots", "snapshot_id"),
        ("discoveries", "discovery_id"),
        ("verifications", "verification_id"),
        ("verification_evidence", "evidence_id"),
        ("review_tasks", "review_task_id"),
        ("processing_jobs", "job_id"),
        ("outbox_events", "event_id"),
        ("consumer_receipts", "receipt_id"),
        ("anonymous_sessions", "session_id"),
        ("searches", "search_id"),
        ("join_requests", "join_request_id"),
        ("audit_log", "audit_id"),
    ):
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT gen_random_uuid()")
    op.execute("DROP FUNCTION uuidv7_generate()")
