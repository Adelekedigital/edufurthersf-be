"""Enforce the parts of the facts JSONB contract that actually crashed a
response when violated, at the boundary instead of only at every read.

_derive_facts (src/app/api/routes.py) sanitizes these same fields on every
read - that stays as defense in depth for rows written before this
migration, or by any future write path that still bypasses build_cycle_facts.
This migration closes the gap for every write from here on: a row that
would trip _derive_facts's guards can no longer be written at all,
regardless of whether it goes through build_cycle_facts or a raw UPDATE.

The facts-is-an-object constraint is the actual root cause fix, not just
another field check: SQLAlchemy's JSONB.none_as_null defaults to False, so
an ORM-level `cycle.facts = None` persists as the JSON null *literal*, not
SQL NULL - the column's own NOT NULL constraint never sees it and doesn't
block it. `row.facts` reading back as Python None (despite the column
being "NOT NULL") is exactly what crashed /search's whole response over
one row in practice. Once facts itself can never be anything but a real
JSON object, that class of bug is closed at the source; every guard this
migration and _derive_facts add on top is defense in depth for the fields
inside it.

deadline_at's ISO-8601 validity is deliberately left unconstrained here -
validating an arbitrary date/time string's format in a plain SQL CHECK is
impractical. `_safe_deadline_at` (routes.py) remains its only guard.

Confirmed against live staging data before writing this: 101/101 published
cycles already satisfy every constraint below, so this validates immediately
rather than needing NOT VALID + a later VALIDATE CONSTRAINT pass.
"""

from alembic import op

revision = "0020_facts_contract_constraints"
down_revision = "0019_search_version_defaults_v2"
branch_labels = None
depends_on = None

_ARRAY_FIELDS = ("destinations", "levels", "field_names")
_FUNDING_TYPES = ("fully_funded", "partial_funding", "tuition_only", "stipend_only")


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE scholarship_cycles
        ADD CONSTRAINT ck_scholarship_cycles_facts_is_object
        CHECK (jsonb_typeof(facts) = 'object')
        """
    )
    for field in _ARRAY_FIELDS:
        op.execute(
            f"""
            ALTER TABLE scholarship_cycles
            ADD CONSTRAINT ck_scholarship_cycles_facts_{field}_is_array
            CHECK (
                facts->'{field}' IS NULL
                OR jsonb_typeof(facts->'{field}') = 'array'
            )
            """
        )
    op.execute(
        """
        ALTER TABLE scholarship_cycles
        ADD CONSTRAINT ck_scholarship_cycles_facts_deadline_precision
        CHECK (facts->>'deadline_precision' IS NULL OR facts->>'deadline_precision' IN ('date', 'datetime'))
        """
    )
    op.execute(
        f"""
        ALTER TABLE scholarship_cycles
        ADD CONSTRAINT ck_scholarship_cycles_facts_funding_type
        CHECK (facts->>'funding_type' IS NULL OR facts->>'funding_type' IN {_FUNDING_TYPES!r})
        """
    )
    op.execute(
        """
        ALTER TABLE scholarship_cycles
        ADD CONSTRAINT ck_scholarship_cycles_facts_expected_reopen_month
        CHECK (
            facts->'expected_reopen_month' IS NULL
            OR (
                jsonb_typeof(facts->'expected_reopen_month') = 'number'
                AND (facts->>'expected_reopen_month')::numeric BETWEEN 1 AND 12
                AND (facts->>'expected_reopen_month')::numeric
                    = trunc((facts->>'expected_reopen_month')::numeric)
            )
        )
        """
    )
    op.execute(
        """
        ALTER TABLE scholarship_cycles
        ADD CONSTRAINT ck_scholarship_cycles_facts_eligibility_note
        CHECK (facts->>'eligibility_note' IS NULL OR jsonb_typeof(facts->'eligibility_note') = 'string')
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE scholarship_cycles DROP CONSTRAINT ck_scholarship_cycles_facts_eligibility_note"
    )
    op.execute(
        "ALTER TABLE scholarship_cycles DROP CONSTRAINT ck_scholarship_cycles_facts_expected_reopen_month"
    )
    op.execute(
        "ALTER TABLE scholarship_cycles DROP CONSTRAINT ck_scholarship_cycles_facts_funding_type"
    )
    op.execute(
        "ALTER TABLE scholarship_cycles DROP CONSTRAINT ck_scholarship_cycles_facts_deadline_precision"
    )
    for field in _ARRAY_FIELDS:
        op.execute(
            f"ALTER TABLE scholarship_cycles DROP CONSTRAINT ck_scholarship_cycles_facts_{field}_is_array"
        )
    op.execute(
        "ALTER TABLE scholarship_cycles DROP CONSTRAINT ck_scholarship_cycles_facts_is_object"
    )
