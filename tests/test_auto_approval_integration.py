"""attempt_auto_approval end to end - a synthetic fully-corroborated,
real-page-verified candidate gets approved and published; a candidate
failing any single gate stays untouched, for a human to pick up normally.

`fetch_and_verify_source` is stubbed at its import site in
`auto_approval.py` (matching this codebase's own monkeypatch-at-import-site
convention, see `test_source_persistence.py`) - the real fetch/AI-Router
mechanics are Phase 2b's own responsibility, already covered there. What's
under test here is the gating logic that composes them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.api.ingestion_schemas import FeedRecord
from app.domain.linking import LinkOutcome
from app.domain.models import (
    AutoApprovalAudit,
    Discovery,
    DiscoveryVerification,
    Provider,
    RecordState,
    ReviewTask,
    Scholarship,
    ScholarshipCycle,
    Source,
)
from app.infra import auto_approval as auto_approval_module
from app.infra.auto_approval import attempt_auto_approval
from app.infra.ingestion import import_feed_records
from app.infra.linking import link_discovery
from tests.conftest import requires_db

pytestmark = requires_db

_EXCERPT = "A £13,000 scholarship for Master's students, deadline March 15, 2027."
_PAGE_TEXT = (
    "This scholarship offers £13,000 to Master's students in the United Kingdom, "
    "deadline March 15, 2027."
)


@dataclass(frozen=True)
class _FakeSettings:
    auto_approve_enabled: bool = True
    auto_approve_min_age_hours: int = 24
    auto_approve_min_corroboration_sources: int = 2
    auto_approve_require_real_page_verification: bool = True
    auto_approve_sample_rate: float = 0.0
    auto_approve_sweep_batch_limit: int = 50


def _configure(monkeypatch, **overrides) -> None:
    monkeypatch.setattr(auto_approval_module, "get_settings", lambda: _FakeSettings(**overrides))


async def _source(db, *, name: str) -> Source:
    source = Source(
        name=name,
        source_type="aggregator",
        authority_grade="C",
        approved_domains=["example.test"],
        active=True,
    )
    db.add(source)
    await db.commit()
    return source


async def _provider(db, *, approved_domains: list[str]) -> Provider:
    provider = Provider(name="UCL", approved_domains=approved_domains)
    db.add(provider)
    await db.commit()
    return provider


def _record(source_id, url: str, title: str, excerpt: str) -> FeedRecord:
    return FeedRecord(source_id=source_id, url=url, title=title, excerpt=excerpt)


def _stub_verification(
    monkeypatch, *, amount_matches: bool = True, deadline_matches: bool | None = True
):
    async def _fake(db, discovery, source):
        verification = DiscoveryVerification(
            discovery_id=discovery.discovery_id,
            fetched_url="https://ucl.ac.uk/award",
            fetch_method="jina",
            page_text=_PAGE_TEXT,
            ai_reextracted_facts=None,
            agreement={"amount_matches": amount_matches, "deadline_matches": deadline_matches},
        )
        db.add(verification)
        await db.commit()
        return verification

    monkeypatch.setattr(auto_approval_module, "fetch_and_verify_source", _fake)


async def _two_corroborating_discoveries(db) -> tuple[Discovery, ReviewTask]:
    first_source = await _source(db, name="ScholarshipRegion")
    second_source = await _source(db, name="Tavily Web Search")
    title = "UCL Mathematics Scholarship"
    await import_feed_records(
        db, [_record(first_source.source_id, "https://a.test/x", title, _EXCERPT)]
    )
    await import_feed_records(
        db, [_record(second_source.source_id, "https://a.test/y", title, _EXCERPT)]
    )
    discoveries = list(await db.scalars(select(Discovery).order_by(Discovery.created_at)))
    original, duplicate = discoveries
    assert await link_discovery(db, original.discovery_id) == LinkOutcome.new_candidate
    assert await link_discovery(db, duplicate.discovery_id) == LinkOutcome.duplicate_pending

    task = await db.scalar(
        select(ReviewTask).where(ReviewTask.discovery_id == original.discovery_id)
    )
    task.draft_recommendation = {"verdict": "ambiguous"}
    await db.refresh(original)
    original.created_at = datetime.now(UTC) - timedelta(hours=48)
    await db.commit()
    await db.refresh(original)
    return original, task


async def test_a_fully_corroborated_and_verified_candidate_gets_auto_approved(
    db, monkeypatch
) -> None:
    _configure(monkeypatch)
    await _provider(db, approved_domains=["ucl.ac.uk"])
    _stub_verification(monkeypatch)
    _discovery, task = await _two_corroborating_discoveries(db)

    outcome = await attempt_auto_approval(db, task.review_task_id)

    assert outcome.approved is True
    assert outcome.scholarship_id is not None
    assert outcome.cycle_id is not None

    scholarship = await db.scalar(
        select(Scholarship).where(Scholarship.scholarship_id == outcome.scholarship_id)
    )
    assert scholarship.lifecycle_state == RecordState.published
    cycle = await db.scalar(
        select(ScholarshipCycle).where(ScholarshipCycle.cycle_id == outcome.cycle_id)
    )
    assert cycle.is_auto_approved is True
    assert cycle.auto_approval_score is not None
    assert cycle.public_status.value == "open_verified"

    audit = await db.scalar(
        select(AutoApprovalAudit).where(AutoApprovalAudit.cycle_id == outcome.cycle_id)
    )
    assert audit is not None
    assert audit.outcome == "not_sampled"

    await db.refresh(_discovery)
    assert _discovery.auto_review_evaluated_at is not None


async def test_insufficient_corroboration_stays_open_for_a_human(db, monkeypatch) -> None:
    _configure(monkeypatch)
    source = await _source(db, name="ScholarshipRegion")
    await import_feed_records(
        db, [_record(source.source_id, "https://a.test/solo", "Solo Award", _EXCERPT)]
    )
    discovery = await db.scalar(select(Discovery))
    assert await link_discovery(db, discovery.discovery_id) == LinkOutcome.new_candidate
    task = await db.scalar(
        select(ReviewTask).where(ReviewTask.discovery_id == discovery.discovery_id)
    )
    task.draft_recommendation = {"verdict": "ambiguous"}
    await db.refresh(discovery)
    discovery.created_at = datetime.now(UTC) - timedelta(hours=48)
    await db.commit()

    outcome = await attempt_auto_approval(db, task.review_task_id)

    assert outcome.approved is False
    assert outcome.reason == "insufficient_corroboration"
    await db.refresh(discovery)
    assert discovery.auto_review_evaluated_at is not None
    assert await db.scalar(select(Scholarship)) is None


async def test_real_page_disagreement_stays_open(db, monkeypatch) -> None:
    _configure(monkeypatch)
    await _provider(db, approved_domains=["ucl.ac.uk"])
    _stub_verification(monkeypatch, amount_matches=False)
    _discovery, task = await _two_corroborating_discoveries(db)

    outcome = await attempt_auto_approval(db, task.review_task_id)

    assert outcome.approved is False
    assert outcome.reason == "page_disagreement"


async def test_no_resolvable_provider_stays_open(db, monkeypatch) -> None:
    _configure(monkeypatch)
    # No Provider registered at all - ucl.ac.uk resolves to nothing.
    _stub_verification(monkeypatch)
    _discovery, task = await _two_corroborating_discoveries(db)

    outcome = await attempt_auto_approval(db, task.review_task_id)

    assert outcome.approved is False
    assert outcome.reason == "provider_not_resolved"


async def test_a_rejected_draft_is_never_evaluated_further(db, monkeypatch) -> None:
    _configure(monkeypatch)
    await _provider(db, approved_domains=["ucl.ac.uk"])
    _stub_verification(monkeypatch)
    _discovery, task = await _two_corroborating_discoveries(db)
    task.draft_recommendation = {"verdict": "reject"}
    await db.commit()

    outcome = await attempt_auto_approval(db, task.review_task_id)

    assert outcome.approved is False
    assert outcome.reason == "draft_rejected"


async def test_a_candidate_younger_than_the_minimum_age_is_left_for_a_later_sweep(
    db, monkeypatch
) -> None:
    _configure(monkeypatch)
    source = await _source(db, name="ScholarshipRegion")
    await import_feed_records(
        db, [_record(source.source_id, "https://a.test/fresh", "Fresh Award", _EXCERPT)]
    )
    discovery = await db.scalar(select(Discovery))
    assert await link_discovery(db, discovery.discovery_id) == LinkOutcome.new_candidate
    task = await db.scalar(
        select(ReviewTask).where(ReviewTask.discovery_id == discovery.discovery_id)
    )
    task.draft_recommendation = {"verdict": "ambiguous"}
    await db.commit()
    # created_at is left at "now" - too young.

    outcome = await attempt_auto_approval(db, task.review_task_id)

    assert outcome.approved is False
    assert outcome.reason == "too_young"
    await db.refresh(discovery)
    # Not marked evaluated - a later sweep, once old enough, gets a real
    # chance rather than being permanently skipped for being early.
    assert discovery.auto_review_evaluated_at is None


async def test_no_deadline_evidence_never_publishes_an_invisible_status_unknown_cycle(
    db, monkeypatch
) -> None:
    """A status_unknown cycle never appears in search results at all - so
    auto-approve requires a real corroborated deadline rather than ever
    publishing one nobody would see."""
    _configure(monkeypatch)
    await _provider(db, approved_domains=["ucl.ac.uk"])
    excerpt_no_deadline = "A £13,000 scholarship for Master's students."
    page_text_no_deadline = (
        "This scholarship offers £13,000 to Master's students in the United Kingdom."
    )

    async def _fake(db, discovery, source):
        verification = DiscoveryVerification(
            discovery_id=discovery.discovery_id,
            fetched_url="https://ucl.ac.uk/award",
            fetch_method="jina",
            page_text=page_text_no_deadline,
            ai_reextracted_facts=None,
            agreement={"amount_matches": True, "deadline_matches": None},
        )
        db.add(verification)
        await db.commit()
        return verification

    monkeypatch.setattr(auto_approval_module, "fetch_and_verify_source", _fake)

    first_source = await _source(db, name="ScholarshipRegion")
    second_source = await _source(db, name="Tavily Web Search")
    await import_feed_records(
        db,
        [
            _record(
                first_source.source_id, "https://a.test/x", "UCL Award", excerpt_no_deadline
            )
        ],
    )
    await import_feed_records(
        db,
        [
            _record(
                second_source.source_id, "https://a.test/y", "UCL Award", excerpt_no_deadline
            )
        ],
    )
    discoveries = list(await db.scalars(select(Discovery).order_by(Discovery.created_at)))
    original, duplicate = discoveries
    assert await link_discovery(db, original.discovery_id) == LinkOutcome.new_candidate
    assert await link_discovery(db, duplicate.discovery_id) == LinkOutcome.duplicate_pending
    task = await db.scalar(
        select(ReviewTask).where(ReviewTask.discovery_id == original.discovery_id)
    )
    task.draft_recommendation = {"verdict": "ambiguous"}
    await db.refresh(original)
    original.created_at = datetime.now(UTC) - timedelta(hours=48)
    await db.commit()

    outcome = await attempt_auto_approval(db, task.review_task_id)

    assert outcome.approved is False
    assert outcome.reason == "no_deadline_evidence"


async def test_no_stated_amount_but_real_cross_source_corroboration_gets_approved(
    db, monkeypatch
) -> None:
    """The actual end-to-end proof of the Phase 2d relaxation: two
    independent sources agree on the identity and the deadline, neither
    states a dollar figure, and the real page agrees on the deadline too -
    corroboration and sanity checks both treat "nothing stated anywhere" as
    a real substitute for a figure, not a failure."""
    _configure(monkeypatch)
    await _provider(db, approved_domains=["ucl.ac.uk"])
    excerpt_no_amount = (
        "A fully funded scholarship for Master's students, deadline March 15, 2027."
    )
    page_text_no_amount = (
        "This fully funded scholarship is open to Master's students in the United Kingdom, "
        "deadline March 15, 2027."
    )

    async def _fake(db, discovery, source):
        verification = DiscoveryVerification(
            discovery_id=discovery.discovery_id,
            fetched_url="https://ucl.ac.uk/award",
            fetch_method="jina",
            page_text=page_text_no_amount,
            ai_reextracted_facts=None,
            agreement={"amount_matches": None, "deadline_matches": True},
        )
        db.add(verification)
        await db.commit()
        return verification

    monkeypatch.setattr(auto_approval_module, "fetch_and_verify_source", _fake)

    first_source = await _source(db, name="ScholarshipRegion")
    second_source = await _source(db, name="Tavily Web Search")
    title = "UCL Award"
    await import_feed_records(
        db, [_record(first_source.source_id, "https://a.test/x", title, excerpt_no_amount)]
    )
    await import_feed_records(
        db, [_record(second_source.source_id, "https://a.test/y", title, excerpt_no_amount)]
    )
    discoveries = list(await db.scalars(select(Discovery).order_by(Discovery.created_at)))
    original, duplicate = discoveries
    assert await link_discovery(db, original.discovery_id) == LinkOutcome.new_candidate
    assert await link_discovery(db, duplicate.discovery_id) == LinkOutcome.duplicate_pending
    task = await db.scalar(
        select(ReviewTask).where(ReviewTask.discovery_id == original.discovery_id)
    )
    task.draft_recommendation = {"verdict": "ambiguous"}
    await db.refresh(original)
    original.created_at = datetime.now(UTC) - timedelta(hours=48)
    await db.commit()
    await db.refresh(original)
    assert original.extracted_facts["funding_mentions"] == []

    outcome = await attempt_auto_approval(db, task.review_task_id)

    assert outcome.approved is True
    cycle = await db.scalar(
        select(ScholarshipCycle).where(ScholarshipCycle.cycle_id == outcome.cycle_id)
    )
    assert cycle.is_auto_approved is True
    assert cycle.public_status.value == "open_verified"
