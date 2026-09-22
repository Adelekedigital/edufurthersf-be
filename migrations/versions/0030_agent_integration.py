"""Integration surface for the Agent platform (edufurther-agent-be).

Three additions, landing together because they are one capability: the
Agent proposes candidates and evidence, and this service records them
without surrendering any of its own authority.

`discovery_evidence` is claim-level provenance - the thing this schema could
not previously answer. `discovery_verifications` (0028) records one fetch;
it cannot say *why we believe this particular deadline*, which is exactly
what a reviewer needs and what an auto-approval audit has to be able to
reconstruct afterwards.

`agent_runs` gives a run a versioned identity. `discoveries.auto_review_evaluated_at`
(0029) is deliberately a one-time marker, which is right for a fixed gate
but wrong for a workflow that will change: a new workflow version has to be
able to reprocess a discovery on purpose, without that being mistaken for a
duplicate submission. The uniqueness is on (discovery_id, workflow_version),
so re-running the *same* version stays idempotent while a *new* version is a
new run.

`discoveries.split_from_discovery_id` records list-page lineage. It is
deliberately a third relationship, not a reuse of an existing one:
`supersedes_discovery_id` means "a re-crawl of this page changed" and
`duplicate_of_discovery_id` means "the same award reported by another
source". Ten scholarships extracted from one blog post are neither - they
are siblings, and chaining them through `supersedes` would turn ten distinct
awards into ten revisions of one.

Nothing here grants the Agent any authority. `agent_outcome` is recorded,
never acted on; `auto_approval.py` is untouched and `AUTO_APPROVE_ENABLED`
remains the only thing that can publish without a human.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0030_agent_integration"
down_revision = "0029_auto_approval_schema"
branch_labels = None
depends_on = None

#: Aggregator, marketplace, blog and search results may support discovery,
#: but they are not equivalent to official evidence. Recording which kind a
#: claim came from is what keeps that distinction available later.
SOURCE_TYPES = (
    "official_page",
    "official_document",
    "aggregator",
    "marketplace",
    "blog_list",
    "search_result",
)

#: The four Agent outcomes. AUTO_CHECK_ELIGIBLE is an input to this
#: service's existing gates, not a publication command.
AGENT_OUTCOMES = (
    "REVIEW_REQUIRED",
    "MORE_EVIDENCE_REQUIRED",
    "AUTO_CHECK_ELIGIBLE",
    "REJECT_RECOMMENDED",
)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return "{} IN ({})".format(column, ", ".join(f"'{value}'" for value in values))


def upgrade() -> None:
    op.add_column(
        "discoveries",
        sa.Column(
            "split_from_discovery_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("discoveries.discovery_id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_discoveries_split_from_discovery_id",
        "discoveries",
        ["split_from_discovery_id"],
    )

    op.create_table(
        "discovery_evidence",
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "discovery_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("discoveries.discovery_id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The fact this evidence supports, e.g. "funding.amount".
        sa.Column("claim_path", sa.String(255), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetch_method", sa.String(20), nullable=True),
        sa.Column("confidence", sa.String(20), nullable=True),
        sa.Column("workflow_run_id", sa.String(128), nullable=False),
        sa.Column("workflow_version", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=True),
        sa.Column("model", sa.String(120), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_check_constraint(
        "ck_discovery_evidence_source_type",
        "discovery_evidence",
        sa.text(_in_list("source_type", SOURCE_TYPES)),
    )
    # A database guarantee, not a code-level check. Evidence submission is an
    # at-least-once path like every other in this service, and 0014's
    # docstring records what a code-only duplicate check cost last time: a
    # 604-row import produced 1,247 excess open review tasks.
    op.create_unique_constraint(
        "uq_discovery_evidence_claim",
        "discovery_evidence",
        ["discovery_id", "claim_path", "source_url", "workflow_run_id"],
    )
    op.create_index(
        "ix_discovery_evidence_discovery_id", "discovery_evidence", ["discovery_id"]
    )

    op.create_table(
        "agent_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "discovery_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("discoveries.discovery_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("workflow_version", sa.String(64), nullable=False),
        sa.Column("agent_outcome", sa.String(32), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=True),
        sa.Column("model", sa.String(120), nullable=True),
        # The Agent's proposal, kept separate from ReviewTask.draft_recommendation
        # for the same reason ai_extracted_facts is kept separate from
        # extracted_facts: different provenance, so a reviewer can weigh them
        # independently rather than being handed one merged opinion.
        sa.Column("recommendation", postgresql.JSONB(), nullable=True),
        sa.Column("correlation_id", sa.String(128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_check_constraint(
        "ck_agent_runs_outcome",
        "agent_runs",
        sa.text(_in_list("agent_outcome", AGENT_OUTCOMES)),
    )
    # Re-running one version is idempotent; a new version is a new run.
    op.create_unique_constraint(
        "uq_agent_runs_discovery_workflow",
        "agent_runs",
        ["discovery_id", "workflow_version"],
    )
    op.create_index("ix_agent_runs_discovery_id", "agent_runs", ["discovery_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_runs_discovery_id", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_discovery_evidence_discovery_id", table_name="discovery_evidence")
    op.drop_table("discovery_evidence")
    op.drop_index("ix_discoveries_split_from_discovery_id", table_name="discoveries")
    op.drop_column("discoveries", "split_from_discovery_id")
