"""Constrain the publication and status columns at the database.

The ORM models these as Python enums, but the columns are plain VARCHAR, so
nothing stopped an out-of-range value written by a migration, a script or a
future code path. The technical design requires the database itself to reject
invalid enums.
"""

from alembic import op

revision = "0007_enum_check_constraints"
down_revision = "0006_uuidv7_defaults"
branch_labels = None
depends_on = None

_CONSTRAINTS = (
    (
        "scholarships",
        "ck_scholarships_lifecycle_state",
        "lifecycle_state",
        ("discovered", "needs_review", "published", "withdrawn"),
    ),
    (
        "scholarship_cycles",
        "ck_scholarship_cycles_public_status",
        "public_status",
        ("open_verified", "expected_to_reopen", "status_unknown"),
    ),
)


def upgrade() -> None:
    for table, name, column, values in _CONSTRAINTS:
        allowed = ", ".join(f"'{value}'" for value in values)
        op.create_check_constraint(name, table, f"{column} IN ({allowed})")


def downgrade() -> None:
    for table, name, _column, _values in _CONSTRAINTS:
        op.drop_constraint(name, table, type_="check")
