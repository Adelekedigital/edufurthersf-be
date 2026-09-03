import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
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
    content_hash: Mapped[str] = mapped_column(String(128))
    raw_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    raw_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_state: Mapped[str] = mapped_column(String(40), default="discovered")
    normalized_identity_key: Mapped[str | None] = mapped_column(
        String(500), nullable=True, index=True
    )
    canonical_scholarship_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (UniqueConstraint("source_page_id", "content_hash"),)


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


class ProcessingJob(TimestampMixin, Base):
    __tablename__ = "processing_jobs"
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    kind: Mapped[str] = mapped_column(String(60))
    dedupe_key: Mapped[str] = mapped_column(String(500), unique=True)
    state: Mapped[str] = mapped_column(String(30), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class OutboxEvent(TimestampMixin, Base):
    __tablename__ = "outbox_events"
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    event_type: Mapped[str] = mapped_column(String(120))
    destination: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    state: Mapped[str] = mapped_column(String(30), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)


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


class Search(TimestampMixin, Base):
    __tablename__ = "searches"
    search_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("anonymous_sessions.session_id"), nullable=True
    )
    filter_digest: Mapped[str] = mapped_column(String(128))
    filters: Mapped[dict] = mapped_column(JSONB, default=dict)
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
