import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.ids import new_uuid7


class Base(DeclarativeBase):
    pass


class RecordState(str, enum.Enum):
    discovered = "discovered"
    needs_review = "needs_review"
    published = "published"
    withdrawn = "withdrawn"


class PublicStatus(str, enum.Enum):
    open_verified = "open_verified"
    expected_to_reopen = "expected_to_reopen"
    status_unknown = "status_unknown"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Provider(TimestampMixin, Base):
    __tablename__ = "providers"
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    name: Mapped[str] = mapped_column(String(255))
    approved_domains: Mapped[list[str]] = mapped_column(JSONB, default=list)


class Scholarship(TimestampMixin, Base):
    __tablename__ = "scholarships"
    scholarship_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("providers.provider_id"))
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(500))
    official_home_url: Mapped[str] = mapped_column(Text)
    #: What kind of award this is (scholarship/fellowship/assistantship/...),
    #: validated against TAXONOMY.award_type - a taxonomy concept like degree
    #: or field, not a DB-level enum, so a new type needs no migration.
    award_type: Mapped[str] = mapped_column(String(30))
    # The migration stores this as VARCHAR. A native PG enum would bind as
    # `$1::recordstate`, a type no migration ever created, so every query
    # filtering on it failed. Keep the Python enum, store it as text.
    lifecycle_state: Mapped[RecordState] = mapped_column(
        Enum(
            RecordState,
            native_enum=False,
            length=30,
            create_constraint=True,
            name="ck_scholarships_lifecycle_state",
            validate_strings=True,
        ),
        default=RecordState.needs_review,
    )
    current_published_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    provider: Mapped[Provider] = relationship()
    cycles: Mapped[list[ScholarshipCycle]] = relationship(back_populates="scholarship")


class ScholarshipCycle(TimestampMixin, Base):
    __tablename__ = "scholarship_cycles"
    __table_args__ = (
        UniqueConstraint("scholarship_id", "provider_cycle_key", "applicant_segment"),
    )
    cycle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    scholarship_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scholarships.scholarship_id"))
    provider_cycle_key: Mapped[str] = mapped_column(String(255))
    applicant_segment: Mapped[str] = mapped_column(String(255), default="default")
    official_cycle_url: Mapped[str] = mapped_column(Text)
    public_status: Mapped[PublicStatus] = mapped_column(
        Enum(
            PublicStatus,
            native_enum=False,
            length=40,
            create_constraint=True,
            name="ck_scholarship_cycles_public_status",
            validate_strings=True,
        )
    )
    status_valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    facts: Mapped[dict] = mapped_column(JSONB, default=dict)
    scholarship: Mapped[Scholarship] = relationship(back_populates="cycles")


class ScholarshipRevision(TimestampMixin, Base):
    __tablename__ = "scholarship_revisions"
    revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    scholarship_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scholarships.scholarship_id"))
    version: Mapped[int] = mapped_column(Integer)
    facts: Mapped[dict] = mapped_column(JSONB, default=dict)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    __table_args__ = (UniqueConstraint("scholarship_id", "version"),)


class Source(TimestampMixin, Base):
    __tablename__ = "sources"
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    name: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(50))
    authority_grade: Mapped[str] = mapped_column(String(1))
    approved_domains: Mapped[list[str]] = mapped_column(JSONB, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class SourcePage(TimestampMixin, Base):
    __tablename__ = "source_pages"
    page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.source_id"))
    normalized_url: Mapped[str] = mapped_column(Text)
    normalized_content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_successful_fetch_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Touched whenever a feed row reports this URL again, independent of
    # whether the fetcher has ever run. Distinct from last_attempted_at, which
    # tracks a direct GET, not the feed re-reporting an already known URL.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (UniqueConstraint("source_id", "normalized_url"),)


class SourceSnapshot(Base):
    __tablename__ = "source_snapshots"
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    page_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_pages.page_id"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    content_hash: Mapped[str] = mapped_column(String(128))
    extractor_version: Mapped[str] = mapped_column(String(50))
    relevant_content: Mapped[dict] = mapped_column(JSONB, default=dict)
    failure_classification: Mapped[str | None] = mapped_column(String(50), nullable=True)


class Discovery(TimestampMixin, Base):
    __tablename__ = "discoveries"
    discovery_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    source_page_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_pages.page_id"))
    # Which import produced this row. Nullable because a discovery can also
    # originate from a direct fetch rather than a feed import.
    crawl_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("crawl_runs.crawl_run_id"), nullable=True
    )
    content_hash: Mapped[str] = mapped_column(String(128))
    raw_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    raw_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The feed's own dates. Discovery/publication signals, never application
    # deadlines: a past Source Posted Date does not mean anything closed.
    source_posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    feed_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_state: Mapped[str] = mapped_column(String(40), default="discovered")
    normalized_identity_key: Mapped[str | None] = mapped_column(
        String(500), nullable=True, index=True
    )
    canonical_scholarship_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # Deterministic, provisional facts a heuristic extractor found in
    # raw_title/raw_excerpt - never a verified fact, purely a reviewer head
    # start. Null until the extract_candidate job has run for this row.
    extracted_facts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # A separate, optional AI Router pass over the same raw text - kept apart
    # from `extracted_facts` rather than merged into it, since the two have
    # different provenance (regex vs. model) and the router "cannot set
    # published or verified state": just as provisional as the regex facts,
    # never more trusted for being newer or model-produced. Null whenever the
    # router wasn't configured, didn't complete, or hasn't run yet.
    ai_extracted_facts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # The prior discovery whose content this row revises. A changed re-crawl of
    # an already known URL creates a new row rather than overwriting the old
    # one, so a decision made from the earlier content stays explainable.
    supersedes_discovery_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("discoveries.discovery_id"), nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (UniqueConstraint("source_page_id", "content_hash"),)


class CrawlRun(TimestampMixin, Base):
    """One import batch's identity, timing, scope and outcome.

    Summarizes a run so an operator can see overall collection health without
    reading every row; QStash delivers and retries the work, this records what
    the work did.
    """

    __tablename__ = "crawl_runs"
    crawl_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    kind: Mapped[str] = mapped_column(String(60), index=True)
    scope: Mapped[dict] = mapped_column(JSONB, default=dict)
    state: Mapped[str] = mapped_column(String(30), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    imported_count: Mapped[int] = mapped_column(Integer, default=0)
    repeated_count: Mapped[int] = mapped_column(Integer, default=0)
    changed_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class DiscoveryQuarantine(Base):
    """A raw feed row that could not become a Discovery, kept rather than dropped.

    An unresolvable source id or an unparsable URL means no SourcePage exists
    to attach a Discovery to, but the row must still be retrievable: quarantine
    only means something if the row survives it.
    """

    __tablename__ = "discovery_quarantine"
    quarantine_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    crawl_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crawl_runs.crawl_run_id"))
    # Not a foreign key: the row may be quarantined precisely because this id
    # does not resolve to any Source.
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    raw_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    raw_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Verification(TimestampMixin, Base):
    __tablename__ = "verifications"
    verification_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scholarship_revisions.revision_id"))
    result: Mapped[str] = mapped_column(String(30))
    policy_version: Mapped[str] = mapped_column(String(50))
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class VerificationEvidence(TimestampMixin, Base):
    __tablename__ = "verification_evidence"
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    verification_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("verifications.verification_id"))
    claim_path: Mapped[str] = mapped_column(String(255))
    asserted_value: Mapped[dict] = mapped_column(JSONB, default=dict)
    evidence_url: Mapped[str] = mapped_column(Text)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    reviewer_decision: Mapped[str] = mapped_column(String(30))


class ReviewTask(TimestampMixin, Base):
    __tablename__ = "review_tasks"
    __table_args__ = (
        # A discovery may only have one live (open, un-annotated) task at a
        # time - concurrent job delivery (QStash redelivery racing a manual
        # run-due sweep, or two overlapping sweeps) must not be able to spawn
        # a second one. Scoped to the same open+unresolved state the
        # application's own check already uses, so a discovery can still gain
        # a fresh task later once its current one is resolved.
        Index(
            "uq_review_tasks_open_per_discovery",
            "discovery_id",
            unique=True,
            postgresql_where=text("state = 'open' AND resolution IS NULL"),
        ),
    )
    review_task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    revision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scholarship_revisions.revision_id"), nullable=True
    )
    discovery_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("discoveries.discovery_id"), nullable=True
    )
    reason: Mapped[str] = mapped_column(String(255))
    priority: Mapped[int] = mapped_column(Integer, default=100)
    state: Mapped[str] = mapped_column(String(30), default="open")
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: prepare_review's drafted proposal (verdict, proposed facts/award_type,
    #: reasoning trail) - never a decision. Null until prepare_review has run.
    draft_recommendation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class ProcessingJob(TimestampMixin, Base):
    __tablename__ = "processing_jobs"
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    kind: Mapped[str] = mapped_column(String(60))
    dedupe_key: Mapped[str] = mapped_column(String(500), unique=True)
    state: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Backoff was computed on failure and thrown away for want of a column, so
    # a retry could run immediately and no sweeper could find due work.
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # A claim that dies mid-flight leaves the row running forever without this;
    # the reconcile sweep returns expired leases to the queue.
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)


class OutboxEvent(TimestampMixin, Base):
    __tablename__ = "outbox_events"
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    event_type: Mapped[str] = mapped_column(String(120))
    # Consumers filter on this. One shared table with mixed destinations is
    # only safe if every reader is scoped to its own.
    destination: Mapped[str] = mapped_column(String(50), index=True)
    # Makes a retried request idempotent: a re-requested response must not
    # emit a second business event for the same logical change.
    dedupe_key: Mapped[str] = mapped_column(String(500), unique=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    state: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConsumerReceipt(TimestampMixin, Base):
    __tablename__ = "consumer_receipts"
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    consumer: Mapped[str] = mapped_column(String(80))
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    __table_args__ = (UniqueConstraint("consumer", "event_id"),)


class AnonymousSession(TimestampMixin, Base):
    __tablename__ = "anonymous_sessions"
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    pseudonymous_id: Mapped[str] = mapped_column(String(128), unique=True)
    consent_state: Mapped[str] = mapped_column(String(30), default="unknown")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Country(TimestampMixin, Base):
    """One ISO 3166-1 country, mirrored from Core's catalogue.

    Core owns country identity. `is_supported_destination` is Finder's, driven
    by verified coverage rather than by anything Core knows, so a sync must
    leave it alone.
    """

    __tablename__ = "countries"
    country_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    code: Mapped[str] = mapped_column(String(2), unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    # Traceability only. Core states reference ids differ per environment, so
    # nothing may resolve a country by this value.
    core_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    is_supported_destination: Mapped[bool] = mapped_column(Boolean, default=False)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Search(TimestampMixin, Base):
    """One evaluated response page.

    A logical search groups its pages by `search_id`; each page is its own row
    with its own `id`, so re-evaluating a page never overwrites what an earlier
    one returned. `result_snapshot` holds the public result objects in the order
    they were returned, which is what makes a later click or a ranking
    complaint explainable after the catalogue has moved on.
    """

    __tablename__ = "searches"
    __table_args__ = (
        UniqueConstraint("search_id", "page_number", name="uq_searches_search_id_page"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid7)
    search_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, default=new_uuid7)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("anonymous_sessions.session_id"), nullable=True
    )
    filter_digest: Mapped[str] = mapped_column(String(128))
    filters: Mapped[dict] = mapped_column(JSONB, default=dict)
    result_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
    snapshot_schema_version: Mapped[str] = mapped_column(String(20), default="snapshot-v1")
    match_policy_version: Mapped[str] = mapped_column(String(50), default="match-v1")
    taxonomy_version: Mapped[str] = mapped_column(String(50), default="taxonomy-v1")
    page_number: Mapped[int] = mapped_column(Integer, default=1)
    requested_limit: Mapped[int] = mapped_column(Integer, default=20)
    returned_count: Mapped[int] = mapped_column(Integer, default=0)
    total_match_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class JoinRequest(TimestampMixin, Base):
    __tablename__ = "join_requests"
    join_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
    core_join_intent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    outcome: Mapped[str] = mapped_column(String(30), default="created")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_log"
    audit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    actor: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(100))
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
