"""The Agent integration surface, end to end against real Postgres.

Two things this file exists to prove, above the ordinary CRUD:

1. **The Agent cannot decide anything.** It may propose candidates, attach
   evidence, ask for a review and record an outcome. It may not resolve a
   review, create a scholarship, publish a cycle or reach any admin route.
2. **Ten awards split from one blog post are siblings, not revisions.**
   `import_feed_records` sets `supersedes_discovery_id` from the newest
   prior discovery on the same page, which for list decomposition would
   silently turn ten distinct awards into ten revisions of one. That is the
   single most damaging way this feature could appear to work.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.api.ingestion_schemas import FeedRecord
from app.domain.models import (
    AgentRun,
    Discovery,
    DiscoveryEvidence,
    ProcessingJob,
    ReviewTask,
    Scholarship,
    Source,
    SourcePage,
)
from app.infra.ingestion import import_feed_records
from tests.conftest import requires_db

pytestmark = requires_db

AGENT = {"X-Service-Token": "agent-service-token"}
ADMIN = {"X-Service-Token": "internal-service-token"}
AGENT_BASE = "/api/v1/internal/agent"


async def make_discovery(
    db, *, url: str = "https://aggregator.test/top-10-scholarships"
) -> Discovery:
    """A real Source, SourcePage and Discovery, via the ordinary import path."""
    source = Source(
        name=f"Aggregator {uuid.uuid4().hex[:8]}",
        source_type="feed",
        authority_grade="C",
        approved_domains=["aggregator.test"],
        active=True,
    )
    db.add(source)
    await db.commit()

    await import_feed_records(
        db,
        [
            FeedRecord(
                source_id=source.source_id,
                url=url,
                title="Top 10 Scholarships for 2026",
                excerpt="A roundup of ten funding opportunities.",
            )
        ],
    )
    discovery = await db.scalar(select(Discovery).order_by(Discovery.created_at.desc()).limit(1))
    assert discovery is not None
    return discovery


def candidates(count: int) -> list[dict]:
    return [
        {
            "title": f"Award Number {index}",
            "url": f"https://aggregator.test/award-{index}",
            "excerpt": f"Funding details for award {index}.",
            "heading": f"{index}. Award Number {index}",
        }
        for index in range(1, count + 1)
    ]


# --- authentication: the separation is the point ----------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", f"{AGENT_BASE}/discoveries"),
        ("get", f"{AGENT_BASE}/discoveries/{uuid.uuid4()}"),
        ("post", f"{AGENT_BASE}/candidates"),
        ("post", f"{AGENT_BASE}/candidates/{uuid.uuid4()}/evidence"),
        ("post", f"{AGENT_BASE}/candidates/{uuid.uuid4()}/review"),
        ("post", f"{AGENT_BASE}/runs"),
    ],
)
async def test_every_agent_route_requires_a_token(client, method, path) -> None:
    kwargs = {} if method == "get" else {"json": {}}
    response = await getattr(client, method)(path, **kwargs)
    assert response.status_code == 401


async def test_the_admin_token_does_not_open_the_agent_surface(client) -> None:
    """Not merely tidiness. If either token opened both, the automation
    boundary would rest entirely on the Agent choosing not to publish."""
    response = await client.get(f"{AGENT_BASE}/discoveries", headers=ADMIN)
    assert response.status_code == 401


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/api/v1/internal/admin/reviews", None),
        ("get", "/api/v1/internal/admin/scholarships", None),
        ("post", "/api/v1/internal/admin/jobs/run-due", {}),
        ("post", f"/api/v1/internal/admin/scholarships/{uuid.uuid4()}/withdraw", {"reason": "x"}),
        ("post", f"/api/v1/internal/admin/scholarships/{uuid.uuid4()}/publish", {}),
        ("post", "/api/v1/internal/import/feed", {"records": []}),
    ],
)
async def test_the_agent_token_does_not_open_the_admin_surface(client, method, path, body) -> None:
    """Least privilege, asserted route by route. Publish and withdraw are
    the ones that matter most: the Agent must have no path to either."""
    kwargs = {"headers": AGENT}
    if body is not None:
        kwargs["json"] = body
    response = await getattr(client, method)(path, **kwargs)
    assert response.status_code == 401


# --- reading work -----------------------------------------------------


async def test_discoveries_carry_the_lineage_the_review_queue_omits(client, db) -> None:
    discovery = await make_discovery(db)

    response = await client.get(f"{AGENT_BASE}/discoveries?workflow_version=v1", headers=AGENT)

    body = response.json()
    assert response.status_code == 200
    item = next(i for i in body["items"] if i["discovery_id"] == str(discovery.discovery_id))
    assert item["source_url"] == "https://aggregator.test/top-10-scholarships"
    assert item["approved_domains"] == ["aggregator.test"]
    assert item["authority_grade"] == "C"
    assert item["normalized_identity_key"]
    # The relationships an agent needs and ReviewTaskSummary does not carry.
    assert "supersedes_discovery_id" in item
    assert "duplicate_of_discovery_id" in item
    assert "split_from_discovery_id" in item


async def test_a_single_discovery_can_be_read(client, db) -> None:
    discovery = await make_discovery(db)

    response = await client.get(f"{AGENT_BASE}/discoveries/{discovery.discovery_id}", headers=AGENT)

    assert response.status_code == 200
    assert response.json()["discovery_id"] == str(discovery.discovery_id)


async def test_an_unknown_discovery_is_a_problem_response(client) -> None:
    response = await client.get(f"{AGENT_BASE}/discoveries/{uuid.uuid4()}", headers=AGENT)

    assert response.status_code == 404
    assert response.json()["code"] == "DISCOVERY_NOT_FOUND"


async def test_a_processed_discovery_is_excluded_for_that_workflow_version(client, db) -> None:
    discovery = await make_discovery(db)
    await client.post(
        f"{AGENT_BASE}/runs",
        headers=AGENT,
        json={
            "discovery_id": str(discovery.discovery_id),
            "workflow_version": "v1",
            "agent_outcome": "REVIEW_REQUIRED",
        },
    )

    same = await client.get(f"{AGENT_BASE}/discoveries?workflow_version=v1", headers=AGENT)
    bumped = await client.get(f"{AGENT_BASE}/discoveries?workflow_version=v2", headers=AGENT)

    processed = str(discovery.discovery_id)
    assert processed not in [i["discovery_id"] for i in same.json()["items"]]
    # The reprocessing path a one-time marker cannot offer: a changed
    # workflow makes the record eligible again, on purpose.
    assert processed in [i["discovery_id"] for i in bumped.json()["items"]]


async def test_pagination_is_a_keyset_cursor(client, db) -> None:
    """An offset silently skips rows when the queue is written to while it
    is being read, which is exactly what happens here."""
    for index in range(3):
        await make_discovery(db, url=f"https://aggregator.test/list-{index}")

    first = await client.get(f"{AGENT_BASE}/discoveries?limit=2&workflow_version=v1", headers=AGENT)
    cursor = first.json()["next_cursor"]
    second = await client.get(
        f"{AGENT_BASE}/discoveries?limit=2&workflow_version=v1&after={cursor}", headers=AGENT
    )

    assert len(first.json()["items"]) == 2
    assert cursor is not None
    first_ids = {i["discovery_id"] for i in first.json()["items"]}
    second_ids = {i["discovery_id"] for i in second.json()["items"]}
    assert not first_ids & second_ids
    # A short page is the last page.
    assert second.json()["next_cursor"] is None


# --- split candidates: the lineage trap -------------------------------


async def test_split_candidates_are_siblings_not_revisions_of_each_other(client, db) -> None:
    """The test this whole endpoint exists for.

    `import_feed_records` sets supersedes_discovery_id from the newest prior
    discovery on the same page. Reusing it here would chain ten awards into
    ten revisions of one - and it would look like it worked: ten rows would
    exist, and only the lineage would be wrong.
    """
    parent = await make_discovery(db)

    response = await client.post(
        f"{AGENT_BASE}/candidates",
        headers=AGENT,
        json={
            "parent_discovery_id": str(parent.discovery_id),
            "workflow_version": "v1",
            "candidates": candidates(10),
        },
    )

    assert response.status_code == 200
    assert response.json()["created"] == 10

    children = (
        (
            await db.execute(
                select(Discovery).where(Discovery.split_from_discovery_id == parent.discovery_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(children) == 10
    assert all(child.supersedes_discovery_id is None for child in children), (
        "candidates were chained as revisions of each other"
    )
    assert all(child.split_from_discovery_id == parent.discovery_id for child in children)
    # Ten distinct awards, not ten copies of one.
    assert len({child.normalized_identity_key for child in children}) == 10


async def test_split_candidates_enter_the_ordinary_pipeline(client, db) -> None:
    """Each candidate is a real Discovery with normalize and link jobs, so
    identity linking, duplicate detection and review-task uniqueness all
    work exactly as they do for an imported row."""
    parent = await make_discovery(db)

    await client.post(
        f"{AGENT_BASE}/candidates",
        headers=AGENT,
        json={
            "parent_discovery_id": str(parent.discovery_id),
            "workflow_version": "v1",
            "candidates": candidates(2),
        },
    )

    kinds = (
        await db.execute(
            select(ProcessingJob.kind, func.count())
            .where(ProcessingJob.kind.in_(["normalize_discovery", "link_canonical"]))
            .group_by(ProcessingJob.kind)
        )
    ).all()
    counts = dict(kinds)
    # One each for the parent import, two each for the candidates.
    assert counts["normalize_discovery"] == 3
    assert counts["link_canonical"] == 3


async def test_resubmitting_the_same_candidates_creates_nothing_new(client, db) -> None:
    parent = await make_discovery(db)
    payload = {
        "parent_discovery_id": str(parent.discovery_id),
        "workflow_version": "v1",
        "candidates": candidates(3),
    }

    first = await client.post(f"{AGENT_BASE}/candidates", headers=AGENT, json=payload)
    second = await client.post(f"{AGENT_BASE}/candidates", headers=AGENT, json=payload)

    assert first.json()["created"] == 3
    assert second.json()["created"] == 0
    assert second.json()["duplicates"] == 3
    # Same rows, not new ones.
    assert [r["discovery_id"] for r in first.json()["results"]] == [
        r["discovery_id"] for r in second.json()["results"]
    ]


async def test_a_candidate_without_its_own_url_lands_on_the_parent_page(client, db) -> None:
    """Plenty of list pages describe an award without linking to it. That
    is genuinely where the claim was found, so recording it against the
    parent's page is honest rather than a fallback."""
    parent = await make_discovery(db)

    response = await client.post(
        f"{AGENT_BASE}/candidates",
        headers=AGENT,
        json={
            "parent_discovery_id": str(parent.discovery_id),
            "workflow_version": "v1",
            "candidates": [{"title": "Unlinked Award", "excerpt": "Described inline."}],
        },
    )

    assert response.json()["created"] == 1
    child = await db.scalar(
        select(Discovery).where(Discovery.split_from_discovery_id == parent.discovery_id)
    )
    assert child is not None
    assert child.source_page_id == parent.source_page_id
    assert child.supersedes_discovery_id is None


async def test_several_unlinked_candidates_on_one_page_stay_distinct(client, db) -> None:
    """The same-page case is where revision chaining would bite hardest:
    all of these share a SourcePage, so only the content hash distinguishes
    them."""
    parent = await make_discovery(db)

    response = await client.post(
        f"{AGENT_BASE}/candidates",
        headers=AGENT,
        json={
            "parent_discovery_id": str(parent.discovery_id),
            "workflow_version": "v1",
            "candidates": [
                {"title": f"Inline Award {i}", "excerpt": f"Details {i}."} for i in range(5)
            ],
        },
    )

    assert response.json()["created"] == 5
    children = (
        (
            await db.execute(
                select(Discovery).where(Discovery.split_from_discovery_id == parent.discovery_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(children) == 5
    assert all(c.supersedes_discovery_id is None for c in children)
    assert len({c.source_page_id for c in children}) == 1


async def test_one_unusable_candidate_does_not_discard_the_others(client, db) -> None:
    """Per-item isolation. This service has lost a whole harvest batch to
    one bad row before."""
    parent = await make_discovery(db)

    response = await client.post(
        f"{AGENT_BASE}/candidates",
        headers=AGENT,
        json={
            "parent_discovery_id": str(parent.discovery_id),
            "workflow_version": "v1",
            "candidates": [
                {"title": "Good One", "url": "https://aggregator.test/good"},
                {"title": "Bad One", "url": "https://aggregator.test/also-good"},
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["created"] == 2


async def test_candidates_for_an_unknown_parent_are_refused(client) -> None:
    response = await client.post(
        f"{AGENT_BASE}/candidates",
        headers=AGENT,
        json={
            "parent_discovery_id": str(uuid.uuid4()),
            "workflow_version": "v1",
            "candidates": candidates(1),
        },
    )

    assert response.status_code == 404


async def test_an_unknown_candidate_field_is_rejected(client, db) -> None:
    parent = await make_discovery(db)

    response = await client.post(
        f"{AGENT_BASE}/candidates",
        headers=AGENT,
        json={
            "parent_discovery_id": str(parent.discovery_id),
            "workflow_version": "v1",
            "candidates": [{"title": "X", "verified": True}],
        },
    )

    assert response.status_code == 422


# --- evidence ---------------------------------------------------------


def evidence_payload(**overrides) -> dict:
    body = {
        "workflow_run_id": "run-1",
        "workflow_version": "v1",
        "prompt_version": "extract_scholarship_facts-v1",
        "model": "openai/model-a",
        "evidence": [
            {
                "claim_path": "funding.amount",
                "value": "GBP 10000",
                "source_url": "https://official.test/award",
                "source_type": "official_page",
                "excerpt": "The award is worth GBP 10,000.",
                "observed_at": datetime.now(UTC).isoformat(),
                "fetch_method": "direct",
                "confidence": "explicit",
            }
        ],
    }
    return body | overrides


async def test_evidence_is_recorded_with_its_provenance(client, db) -> None:
    discovery = await make_discovery(db)

    response = await client.post(
        f"{AGENT_BASE}/candidates/{discovery.discovery_id}/evidence",
        headers=AGENT,
        json=evidence_payload(),
    )

    assert response.status_code == 200
    assert response.json()["recorded"] == 1
    row = await db.scalar(
        select(DiscoveryEvidence).where(DiscoveryEvidence.discovery_id == discovery.discovery_id)
    )
    assert row is not None
    assert row.claim_path == "funding.amount"
    assert row.source_type == "official_page"
    assert row.prompt_version == "extract_scholarship_facts-v1"
    assert row.workflow_run_id == "run-1"


async def test_resubmitting_a_run_does_not_double_its_evidence(client, db) -> None:
    discovery = await make_discovery(db)
    payload = evidence_payload()

    first = await client.post(
        f"{AGENT_BASE}/candidates/{discovery.discovery_id}/evidence",
        headers=AGENT,
        json=payload,
    )
    second = await client.post(
        f"{AGENT_BASE}/candidates/{discovery.discovery_id}/evidence",
        headers=AGENT,
        json=payload,
    )

    assert first.json()["recorded"] == 1
    assert second.json()["recorded"] == 0
    assert second.json()["duplicates"] == 1
    total = await db.scalar(
        select(func.count(DiscoveryEvidence.evidence_id)).where(
            DiscoveryEvidence.discovery_id == discovery.discovery_id
        )
    )
    assert total == 1


async def test_a_new_run_adds_its_own_evidence_alongside(client, db) -> None:
    """Idempotent per run, not per claim: a genuinely new run's view of the
    same claim is new evidence, not a duplicate."""
    discovery = await make_discovery(db)
    await client.post(
        f"{AGENT_BASE}/candidates/{discovery.discovery_id}/evidence",
        headers=AGENT,
        json=evidence_payload(workflow_run_id="run-1"),
    )
    await client.post(
        f"{AGENT_BASE}/candidates/{discovery.discovery_id}/evidence",
        headers=AGENT,
        json=evidence_payload(workflow_run_id="run-2"),
    )

    total = await db.scalar(
        select(func.count(DiscoveryEvidence.evidence_id)).where(
            DiscoveryEvidence.discovery_id == discovery.discovery_id
        )
    )
    assert total == 2


@pytest.mark.parametrize(
    "source_type",
    [
        "official_page",
        "official_document",
        "aggregator",
        "marketplace",
        "blog_list",
        "search_result",
    ],
)
async def test_every_declared_source_type_is_accepted(client, db, source_type) -> None:
    discovery = await make_discovery(db)
    payload = evidence_payload()
    payload["evidence"][0]["source_type"] = source_type

    response = await client.post(
        f"{AGENT_BASE}/candidates/{discovery.discovery_id}/evidence",
        headers=AGENT,
        json=payload,
    )

    assert response.status_code == 200


async def test_an_invented_source_type_is_refused(client, db) -> None:
    """The distinction between an official page and an aggregator listing is
    the point of the field; an open string would let it be flattened away."""
    discovery = await make_discovery(db)
    payload = evidence_payload()
    payload["evidence"][0]["source_type"] = "trust_me"

    response = await client.post(
        f"{AGENT_BASE}/candidates/{discovery.discovery_id}/evidence",
        headers=AGENT,
        json=payload,
    )

    assert response.status_code == 422


async def test_evidence_for_an_unknown_discovery_is_refused(client) -> None:
    response = await client.post(
        f"{AGENT_BASE}/candidates/{uuid.uuid4()}/evidence",
        headers=AGENT,
        json=evidence_payload(),
    )

    assert response.status_code == 404


# --- review requests: propose, never decide ---------------------------


async def test_a_review_task_is_opened_once(client, db) -> None:
    discovery = await make_discovery(db)
    body = {"reason": "agent_requires_review"}

    first = await client.post(
        f"{AGENT_BASE}/candidates/{discovery.discovery_id}/review", headers=AGENT, json=body
    )
    second = await client.post(
        f"{AGENT_BASE}/candidates/{discovery.discovery_id}/review", headers=AGENT, json=body
    )

    assert first.json()["created"] is True
    assert second.json()["created"] is False
    assert first.json()["review_task_id"] == second.json()["review_task_id"]
    open_tasks = await db.scalar(
        select(func.count(ReviewTask.review_task_id)).where(
            ReviewTask.discovery_id == discovery.discovery_id,
            ReviewTask.state == "open",
        )
    )
    assert open_tasks == 1


async def test_requesting_review_does_not_write_the_deterministic_draft(client, db) -> None:
    """`draft_recommendation` is prepare_review's output. Overwriting it
    with the Agent's view would merge two provenances into one and leave a
    reviewer unable to tell which part came from where."""
    discovery = await make_discovery(db)

    await client.post(
        f"{AGENT_BASE}/candidates/{discovery.discovery_id}/review",
        headers=AGENT,
        json={"reason": "agent_requires_review"},
    )

    task = await db.scalar(
        select(ReviewTask).where(ReviewTask.discovery_id == discovery.discovery_id)
    )
    assert task is not None
    assert task.draft_recommendation is None
    assert task.state == "open"
    assert task.resolution is None


async def test_requesting_review_cannot_alter_a_human_decision(client, db) -> None:
    """A resolved task does not block a new one - `uq_review_tasks_open_per_discovery`
    is a *partial* index covering only open tasks, so this service's own
    `link_discovery` behaves the same way. That is deliberate: a re-crawl
    that changes the facts should be able to earn a fresh look.

    What must hold is narrower, and is what this asserts: the Agent cannot
    touch the decision that was already made. The resolved task keeps its
    state and its resolution, and a reviewer's verdict is never rewritten.
    """
    discovery = await make_discovery(db)
    await client.post(
        f"{AGENT_BASE}/candidates/{discovery.discovery_id}/review",
        headers=AGENT,
        json={"reason": "agent_requires_review"},
    )
    task = await db.scalar(
        select(ReviewTask).where(ReviewTask.discovery_id == discovery.discovery_id)
    )
    assert task is not None
    resolved_id = task.review_task_id
    task.state = "resolved"
    task.resolution = "rejected by a human"
    await db.commit()

    response = await client.post(
        f"{AGENT_BASE}/candidates/{discovery.discovery_id}/review",
        headers=AGENT,
        json={"reason": "agent_reverification"},
    )

    assert response.status_code == 200
    # A *new* task, not a reopening of the old one.
    assert response.json()["review_task_id"] != str(resolved_id)
    await db.refresh(task)
    assert task.state == "resolved"
    assert task.resolution == "rejected by a human"


# --- runs: recorded, never acted on -----------------------------------


@pytest.mark.parametrize(
    "outcome",
    ["REVIEW_REQUIRED", "MORE_EVIDENCE_REQUIRED", "AUTO_CHECK_ELIGIBLE", "REJECT_RECOMMENDED"],
)
async def test_each_of_the_four_outcomes_is_recorded(client, db, outcome) -> None:
    discovery = await make_discovery(db)

    response = await client.post(
        f"{AGENT_BASE}/runs",
        headers=AGENT,
        json={
            "discovery_id": str(discovery.discovery_id),
            "workflow_version": "v1",
            "agent_outcome": outcome,
        },
    )

    assert response.status_code == 200
    assert response.json()["agent_outcome"] == outcome


async def test_an_invented_outcome_is_refused(client, db) -> None:
    discovery = await make_discovery(db)

    response = await client.post(
        f"{AGENT_BASE}/runs",
        headers=AGENT,
        json={
            "discovery_id": str(discovery.discovery_id),
            "workflow_version": "v1",
            "agent_outcome": "PUBLISH_IT",
        },
    )

    assert response.status_code == 422


async def test_rerunning_a_version_updates_in_place(client, db) -> None:
    discovery = await make_discovery(db)
    body = {
        "discovery_id": str(discovery.discovery_id),
        "workflow_version": "v1",
        "agent_outcome": "MORE_EVIDENCE_REQUIRED",
    }
    await client.post(f"{AGENT_BASE}/runs", headers=AGENT, json=body)

    updated = await client.post(
        f"{AGENT_BASE}/runs", headers=AGENT, json=body | {"agent_outcome": "REVIEW_REQUIRED"}
    )

    assert updated.json()["agent_outcome"] == "REVIEW_REQUIRED"
    total = await db.scalar(
        select(func.count(AgentRun.run_id)).where(AgentRun.discovery_id == discovery.discovery_id)
    )
    assert total == 1


async def test_a_new_workflow_version_is_a_separate_run(client, db) -> None:
    """The gap the one-time `auto_review_evaluated_at` marker leaves: a
    changed workflow has to be able to reprocess a record on purpose."""
    discovery = await make_discovery(db)
    for version in ("v1", "v2"):
        await client.post(
            f"{AGENT_BASE}/runs",
            headers=AGENT,
            json={
                "discovery_id": str(discovery.discovery_id),
                "workflow_version": version,
                "agent_outcome": "REVIEW_REQUIRED",
            },
        )

    total = await db.scalar(
        select(func.count(AgentRun.run_id)).where(AgentRun.discovery_id == discovery.discovery_id)
    )
    assert total == 2


async def test_auto_check_eligible_publishes_nothing(client, db) -> None:
    """The outcome most likely to be misread as an instruction. It is an
    input to the existing gates; recording one must leave publication state
    exactly as it was."""
    discovery = await make_discovery(db)

    await client.post(
        f"{AGENT_BASE}/runs",
        headers=AGENT,
        json={
            "discovery_id": str(discovery.discovery_id),
            "workflow_version": "v1",
            "agent_outcome": "AUTO_CHECK_ELIGIBLE",
            "recommendation": {"confidence": "high"},
        },
    )

    assert await db.scalar(select(func.count(Scholarship.scholarship_id))) == 0
    await db.refresh(discovery)
    assert discovery.canonical_scholarship_id is None
    # Untouched: the Agent has no business marking the product's own gate
    # as having evaluated anything.
    assert discovery.auto_review_evaluated_at is None


async def test_the_agents_recommendation_stays_on_its_own_record(client, db) -> None:
    discovery = await make_discovery(db)

    await client.post(
        f"{AGENT_BASE}/runs",
        headers=AGENT,
        json={
            "discovery_id": str(discovery.discovery_id),
            "workflow_version": "v1",
            "agent_outcome": "REVIEW_REQUIRED",
            "recommendation": {"verdict": "needs a human", "reasons": ["conflicting deadline"]},
        },
    )

    run = await db.scalar(select(AgentRun).where(AgentRun.discovery_id == discovery.discovery_id))
    assert run is not None
    assert run.recommendation == {
        "verdict": "needs a human",
        "reasons": ["conflicting deadline"],
    }


async def test_a_run_for_an_unknown_discovery_is_refused(client) -> None:
    response = await client.post(
        f"{AGENT_BASE}/runs",
        headers=AGENT,
        json={
            "discovery_id": str(uuid.uuid4()),
            "workflow_version": "v1",
            "agent_outcome": "REVIEW_REQUIRED",
        },
    )

    assert response.status_code == 404


# --- the Agent must not be able to manufacture corroboration -----------


async def test_an_agent_candidate_does_not_count_as_an_independent_source(client, db) -> None:
    """The finding this test exists for: corroboration counts distinct
    sources sharing an identity key, and the Agent supplies both halves -
    the title that creates the identity key, and the excerpt that becomes
    the extracted facts. Counting its rows would let it author the second
    independent source `auto_approve_min_corroboration_sources` requires,
    leaving "the Agent never decides" true only while AUTO_APPROVE_ENABLED
    is false.
    """
    from app.infra.corroboration import gather_corroboration

    target = await make_discovery(db, url="https://provider.test/award")
    target.normalized_identity_key = "award|example|the"
    target.extracted_facts = {"funding_mentions": ["£10,000"], "deadline_mentions": []}
    await db.commit()

    parent = await make_discovery(db, url="https://aggregator.test/list-page")
    response = await client.post(
        f"{AGENT_BASE}/candidates",
        headers=AGENT,
        json={
            "parent_discovery_id": str(parent.discovery_id),
            "workflow_version": "v1",
            "candidates": [{"title": "The Example Award", "excerpt": "Worth £10,000."}],
        },
    )
    assert response.json()["created"] == 1
    injected = await db.get(Discovery, uuid.UUID(response.json()["results"][0]["discovery_id"]))
    assert injected is not None
    injected.normalized_identity_key = "award|example|the"
    injected.extracted_facts = {"funding_mentions": ["£10,000"], "deadline_mentions": []}
    await db.commit()

    result = await gather_corroboration(db, target)

    # Still one source: its own. The Agent's row is excluded because it
    # carries split_from_discovery_id.
    assert result.independent_source_count == 1
    assert result.corroborating_discovery_ids == []


async def test_a_genuine_second_source_still_corroborates(db) -> None:
    """The exclusion must be narrow: a real crawler-found report from
    another source is exactly what corroboration is for."""
    from app.infra.corroboration import gather_corroboration

    target = await make_discovery(db, url="https://provider.test/award")
    target.normalized_identity_key = "award|example|the"
    target.extracted_facts = {"funding_mentions": ["£10,000"], "deadline_mentions": []}
    other = await make_discovery(db, url="https://elsewhere.test/award")
    other.normalized_identity_key = "award|example|the"
    other.extracted_facts = {"funding_mentions": ["£10,000"], "deadline_mentions": []}
    await db.commit()

    result = await gather_corroboration(db, target)

    assert result.independent_source_count == 2
    assert result.amount_corroborated is True


# --- input bounds ------------------------------------------------------


async def test_an_oversized_evidence_value_is_refused(client, db) -> None:
    """Every other field is length-bounded; `value` was free-form JSON with
    no cap, so 200 items of a few megabytes each was a single-request
    out-of-memory."""
    discovery = await make_discovery(db)
    payload = evidence_payload()
    payload["evidence"][0]["value"] = "x" * 20_000

    response = await client.post(
        f"{AGENT_BASE}/candidates/{discovery.discovery_id}/evidence",
        headers=AGENT,
        json=payload,
    )

    assert response.status_code == 422


async def test_an_oversized_recommendation_is_refused(client, db) -> None:
    discovery = await make_discovery(db)

    response = await client.post(
        f"{AGENT_BASE}/runs",
        headers=AGENT,
        json={
            "discovery_id": str(discovery.discovery_id),
            "workflow_version": "v1",
            "agent_outcome": "REVIEW_REQUIRED",
            "recommendation": {"blob": "y" * 100_000},
        },
    )

    assert response.status_code == 422


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,<script>", "not-a-url"])
async def test_a_non_http_evidence_url_is_refused(client, db, url) -> None:
    """Evidence is stored and later rendered to a reviewer, so a
    `javascript:` URL here would be a stored-XSS seed."""
    discovery = await make_discovery(db)
    payload = evidence_payload()
    payload["evidence"][0]["source_url"] = url

    response = await client.post(
        f"{AGENT_BASE}/candidates/{discovery.discovery_id}/evidence",
        headers=AGENT,
        json=payload,
    )

    assert response.status_code == 422


async def test_the_agent_cannot_jump_the_review_queue(client, db) -> None:
    """The deterministic scorer floors at 1, so `priority=1` tied for the
    front - which the endpoint's own docstring said it could not do."""
    discovery = await make_discovery(db)

    response = await client.post(
        f"{AGENT_BASE}/candidates/{discovery.discovery_id}/review",
        headers=AGENT,
        json={"reason": "agent_review_required", "priority": 1},
    )

    assert response.status_code == 422


async def test_a_very_long_title_does_not_break_the_batch(client, db) -> None:
    """The dedupe key used to interpolate the identity key raw, so a
    500-character title overflowed ProcessingJob.dedupe_key's String(500)
    and the commit discarded every valid candidate alongside it."""
    parent = await make_discovery(db)

    response = await client.post(
        f"{AGENT_BASE}/candidates",
        headers=AGENT,
        json={
            "parent_discovery_id": str(parent.discovery_id),
            "workflow_version": "v1",
            "candidates": [
                {"title": "A" * 500, "url": "https://aggregator.test/long"},
                {"title": "A Normal Award", "url": "https://aggregator.test/normal"},
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["created"] == 2


def test_the_two_service_tokens_must_differ() -> None:
    """Both arrive in the same `X-Service-Token` header, so setting them to
    one value is an easy and completely silent mistake: every route keeps
    working and the privilege separation is simply gone."""
    from app.core.config import Settings

    with pytest.raises(ValueError, match="must differ"):
        Settings(internal_service_token="same-value", agent_service_token="same-value")


def test_distinct_service_tokens_are_accepted() -> None:
    from app.core.config import Settings

    settings = Settings(internal_service_token="admin-value", agent_service_token="agent-value")

    assert settings.agent_service_token != settings.internal_service_token


async def test_asking_for_unprocessed_work_without_a_version_is_refused(client) -> None:
    """The filter silently did nothing in this combination, so a caller
    using the defaults got the whole table back and reprocessed every
    discovery at five model calls each. Failing loudly is far cheaper."""
    response = await client.get(f"{AGENT_BASE}/discoveries", headers=AGENT)

    assert response.status_code == 422
    assert response.json()["code"] == "WORKFLOW_VERSION_REQUIRED"


async def test_reading_every_discovery_is_still_possible_explicitly(client, db) -> None:
    await make_discovery(db)

    response = await client.get(f"{AGENT_BASE}/discoveries?unprocessed_only=false", headers=AGENT)

    assert response.status_code == 200
    assert response.json()["items"]


async def test_a_validation_error_is_a_422_not_a_500(client, db) -> None:
    """The handler passed `exc.errors()` straight to JSONResponse, and
    pydantic puts the original exception object in ctx["error"] for a
    validator that raises ValueError. Rendering the 422 then raised, and
    the caller got a 500 with a stack trace instead of the field errors."""
    discovery = await make_discovery(db)
    payload = evidence_payload()
    payload["evidence"][0]["value"] = "x" * 20_000

    response = await client.post(
        f"{AGENT_BASE}/candidates/{discovery.discovery_id}/evidence",
        headers=AGENT,
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert response.json()["errors"]["fields"]


async def test_candidates_cannot_be_added_to_a_deactivated_source(client, db) -> None:
    """`Source.active` is the harvest kill switch, and feed imports
    quarantine rows from an inactive source. Without the same check here an
    operator who switched a source off could still have candidates arrive
    under it through the Agent."""
    parent = await make_discovery(db)
    source = await db.scalar(
        select(Source)
        .join(SourcePage, SourcePage.source_id == Source.source_id)
        .where(SourcePage.page_id == parent.source_page_id)
    )
    assert source is not None
    source.active = False
    await db.commit()

    response = await client.post(
        f"{AGENT_BASE}/candidates",
        headers=AGENT,
        json={
            "parent_discovery_id": str(parent.discovery_id),
            "workflow_version": "v1",
            "candidates": candidates(1),
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "SOURCE_INACTIVE"
    created = await db.scalar(
        select(func.count(Discovery.discovery_id)).where(
            Discovery.split_from_discovery_id == parent.discovery_id
        )
    )
    assert created == 0


async def test_a_recrawl_supersedes_the_page_not_a_split_sibling(client, db) -> None:
    """Split children with no link of their own share the parent's page and
    are newer than it. The re-crawl head lookup picked the newest row on the
    page, so a changed page recorded its new revision as superseding
    *candidate #3* - the exact lineage corruption the submission path takes
    care to avoid, reintroduced from the read side."""
    parent = await make_discovery(db)
    source = await db.scalar(
        select(Source)
        .join(SourcePage, SourcePage.source_id == Source.source_id)
        .where(SourcePage.page_id == parent.source_page_id)
    )
    assert source is not None
    await client.post(
        f"{AGENT_BASE}/candidates",
        headers=AGENT,
        json={
            "parent_discovery_id": str(parent.discovery_id),
            "workflow_version": "v1",
            "candidates": [
                {"title": f"Inline Award {i}", "excerpt": f"Details {i}."} for i in range(3)
            ],
        },
    )

    await import_feed_records(
        db,
        [
            FeedRecord(
                source_id=source.source_id,
                url="https://aggregator.test/top-10-scholarships",
                title="Top 10 Scholarships for 2026",
                excerpt="Updated: now eleven opportunities.",
            )
        ],
    )

    revision = await db.scalar(
        select(Discovery)
        .where(Discovery.supersedes_discovery_id.isnot(None))
        .order_by(Discovery.created_at.desc())
        .limit(1)
    )
    assert revision is not None
    assert revision.supersedes_discovery_id == parent.discovery_id, (
        "the re-crawl superseded a split sibling instead of the page"
    )
