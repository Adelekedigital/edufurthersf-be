"""Where a provider institution/organization is actually based.

Nullable, no backfill: unlike award_type (which every existing record could
be assigned from its own known nature), a provider's real country is a fact
that needs looking up per provider, not something safe to guess from what's
already stored. Left null for every existing provider until that lookup is
actually done, per the same no-taxonomy-forcing rule the field/origin
tagging backfill followed.
"""

import sqlalchemy as sa
from alembic import op

revision = "0018_provider_country"
down_revision = "0017_match_explanations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("providers", sa.Column("country", sa.String(3), nullable=True))


def downgrade() -> None:
    op.drop_column("providers", "country")
