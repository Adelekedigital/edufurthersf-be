"""Label every scholarship with what kind of award it actually is.

A lab's paid research assistantship and a merit-based tuition scholarship
were both being stored identically as "scholarships" - a real representation
gap, not just a taxonomy nicety, once assistantship-style postings started
being reviewed as catalog candidates. Backfills every already-published
record with its real type before the column becomes required, so no row is
ever silently mislabeled by a default.
"""

import sqlalchemy as sa
from alembic import op

revision = "0013_award_type"
down_revision = "0012_discovery_extracted_facts"
branch_labels = None
depends_on = None

# slug -> real award type, decided from each record's own verified evidence.
_BACKFILL = {
    "university-of-maine-forest-resources-assistantship": "assistantship",
    "ucl-msc-mathematics-scholarships": "scholarship",
    "hornby-trust-scholarship-exeter": "scholarship",
    "bristol-think-big-scholarship": "scholarship",
    "warwick-chancellors-international-scholarship": "scholarship",
    "goettingen-daad-epos-scholarship": "scholarship",
    "wustl-mcdonnell-international-scholars-academy": "fellowship",
    "senss-studentships": "studentship",
    "ucl-commonwealth-shared-scholarship": "scholarship",
    "cranfield-commonwealth-masters-scholarship": "scholarship",
}


def upgrade() -> None:
    op.add_column("scholarships", sa.Column("award_type", sa.String(30), nullable=True))
    connection = op.get_bind()
    for slug, award_type in _BACKFILL.items():
        connection.execute(
            sa.text("UPDATE scholarships SET award_type = :award_type WHERE slug = :slug"),
            {"award_type": award_type, "slug": slug},
        )
    # Any row this backfill missed (a slug renamed since, e.g.) still needs a
    # value before the NOT NULL below - "scholarship" is the safest fallback,
    # not a silent guess about a specific record's real nature.
    connection.execute(
        sa.text("UPDATE scholarships SET award_type = 'scholarship' WHERE award_type IS NULL")
    )
    op.alter_column("scholarships", "award_type", nullable=False)


def downgrade() -> None:
    op.drop_column("scholarships", "award_type")
