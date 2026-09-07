"""Distinguish "went stale and was auto-downgraded" from "a reviewer
published this as status_unknown on purpose" - found in review of 0021:
without this, once refresh_status downgrades an open_verified cycle for
evidence staleness, nothing ever restores it even after reverify_due later
reconfirms the page is unchanged, since evaluate_public_status only ever
transitions *away* from open_verified, never back to it, and reusing that
same read-time function to decide "should this be restored" is tautological
once the stored status is already status_unknown (it always agrees with
itself). A plain boolean, set only by refresh_status's own staleness
downgrade and cleared only by reverify_due's own restoration, is enough:
neither a reviewer's own status_unknown choice nor a downgrade for an
already-passed deadline (permanent, never restorable) ever sets it.

Backfilled false for every existing row - correct either way, since no
code path wrote a staleness-downgrade before this migration existed.
"""

import sqlalchemy as sa
from alembic import op

revision = "0022_cycle_auto_downgraded"
down_revision = "0021_cycle_reverification_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scholarship_cycles",
        sa.Column("auto_downgraded", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("scholarship_cycles", "auto_downgraded", server_default=None)


def downgrade() -> None:
    op.drop_column("scholarship_cycles", "auto_downgraded")
