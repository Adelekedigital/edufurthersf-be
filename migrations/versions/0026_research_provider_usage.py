"""Add research_provider_usage: per-provider monthly call budgets.

Tracks calls-used-this-calendar-month per external research API (Tavily,
Jina.ai) so app/infra/research_budget.py can enforce a real cap instead of
nothing tracking usage against an external quota at all, as was true before.
"""

import sqlalchemy as sa
from alembic import op

revision = "0026_research_provider_usage"
down_revision = "0025_discovery_duplicate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_provider_usage",
        sa.Column("provider", sa.String(50), primary_key=True),
        sa.Column("period_key", sa.String(20), primary_key=True),
        sa.Column("calls_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("research_provider_usage")
