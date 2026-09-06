"""POST /scholarships/{identifier}: a match_explanation elaborating on the
deterministic decision, cached per (cycle, searcher profile) from day one."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy import select

from app.api.routes import match_explanation_limiter
from app.domain.ai_router import AIRouterOutcome, AIRouterResponse
from app.domain.models import (
    MatchExplanation,
    Provider,
    PublicStatus,
    RecordState,
    Scholarship,
    ScholarshipCycle,
)
from app.infra import match_explanations as match_explanations_module
from tests.conftest import requires_db

pytestmark = requires_db

FACTS = {
    "destinations": ["CA"],
    "levels": ["masters"],
    "origin_mode": "unrestricted",
    "field_mode": "restricted",
    "fields": ["ict"],
    "evidence_fresh": True,
}

PROFILE = {"origin_country": "NG", "program_level": "masters", "field": "ict"}


@dataclass(frozen=True)
class _FakeSettings:
    ai_router_base_url: str | None
    ai_router_private_key_pem: str | None
    ai_router_key_id: str | None


@pytest.fixture(autouse=True)
def _reset_limiter():
    match_explanation_limiter._requests.clear()
    yield
    match_explanation_limiter._requests.clear()


async def _publish(db, *, slug: str = "award-a") -> ScholarshipCycle:
    provider = Provider(name="Example University", approved_domains=["example.test"])
    db.add(provider)
    await db.flush()
    scholarship = Scholarship(
        provider_id=provider.provider_id,
        slug=slug,
        name="Award A",
        official_home_url="https://example.test/award",
        award_type="scholarship",
        lifecycle_state=RecordState.published,
    )
    db.add(scholarship)
    await db.flush()
    cycle = ScholarshipCycle(
        scholarship_id=scholarship.scholarship_id,
        provider_cycle_key=f"{slug}-2026",
        official_cycle_url="https://example.test/award/apply",
        public_status=PublicStatus.open_verified,
        facts=dict(FACTS),
    )
    db.add(cycle)
    await db.commit()
    await db.refresh(cycle)
    return cycle


async def test_get_never_populates_an_explanation(db, client) -> None:
    cycle = await _publish(db)
    response = await client.get(f"/api/v1/scholarships/{cycle.scholarship_id}")
    assert response.status_code == 200, response.text
    assert response.json()["match_explanation"] is None


async def test_post_without_ai_router_configured_returns_no_explanation(db, client) -> None:
    cycle = await _publish(db)
    response = await client.post(
        f"/api/v1/scholarships/{cycle.scholarship_id}", json=PROFILE
    )
    assert response.status_code == 200, response.text
    assert response.json()["match_explanation"] is None


async def test_a_non_matching_profile_never_calls_the_router(db, client, monkeypatch) -> None:
    """Wrong degree level - not a deterministic match at all - so there is
    nothing true to explain, and the router must not even be asked."""
    cycle = await _publish(db)
    called = False

    async def _fake_get_match_explanation(*args, **kwargs):
        nonlocal called
        called = True
        return "should never be reached"

    monkeypatch.setattr(
        "app.api.routes.get_match_explanation", _fake_get_match_explanation
    )
    response = await client.post(
        f"/api/v1/scholarships/{cycle.scholarship_id}",
        json={**PROFILE, "program_level": "doctorate"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["match_explanation"] is None
    assert called is False


async def test_a_matching_profile_gets_and_caches_an_explanation(db, client, monkeypatch) -> None:
    cycle = await _publish(db)
    monkeypatch.setattr(
        match_explanations_module,
        "get_settings",
        lambda: _FakeSettings("https://router.test", "fake-pem", "kid-1"),
    )
    calls = 0

    async def _fake_execute(self, request):
        nonlocal calls
        calls += 1
        return AIRouterResponse(
            request_id="req-1",
            outcome=AIRouterOutcome.completed,
            output={"explanation": "This fits your ICT masters profile.", "evidence": []},
            model_policy_version="v1",
            trace_reference=None,
        )

    monkeypatch.setattr(match_explanations_module.AIRouterClient, "execute", _fake_execute)

    first = await client.post(f"/api/v1/scholarships/{cycle.scholarship_id}", json=PROFILE)
    assert first.status_code == 200, first.text
    assert first.json()["match_explanation"] == "This fits your ICT masters profile."
    assert calls == 1

    stored = await db.scalar(
        select(MatchExplanation).where(MatchExplanation.cycle_id == cycle.cycle_id)
    )
    assert stored is not None
    assert stored.explanation == "This fits your ICT masters profile."

    # Second request, same profile - must be served from cache, not a second call.
    second = await client.post(f"/api/v1/scholarships/{cycle.scholarship_id}", json=PROFILE)
    assert second.status_code == 200, second.text
    assert second.json()["match_explanation"] == "This fits your ICT masters profile."
    assert calls == 1


async def test_a_republish_that_changes_facts_invalidates_the_cache(
    db, client, monkeypatch
) -> None:
    cycle = await _publish(db)
    monkeypatch.setattr(
        match_explanations_module,
        "get_settings",
        lambda: _FakeSettings("https://router.test", "fake-pem", "kid-1"),
    )
    calls = 0

    async def _fake_execute(self, request):
        nonlocal calls
        calls += 1
        return AIRouterResponse(
            request_id=f"req-{calls}",
            outcome=AIRouterOutcome.completed,
            output={"explanation": f"explanation-{calls}", "evidence": []},
            model_policy_version="v1",
            trace_reference=None,
        )

    monkeypatch.setattr(match_explanations_module.AIRouterClient, "execute", _fake_execute)

    first = await client.post(f"/api/v1/scholarships/{cycle.scholarship_id}", json=PROFILE)
    assert first.json()["match_explanation"] == "explanation-1"

    cycle.facts = {**cycle.facts, "eligibility_note": "Something changed."}
    db.add(cycle)
    await db.commit()

    second = await client.post(f"/api/v1/scholarships/{cycle.scholarship_id}", json=PROFILE)
    assert second.json()["match_explanation"] == "explanation-2"
    assert calls == 2


async def test_router_failure_degrades_to_no_explanation_not_a_failed_request(
    db, client, monkeypatch
) -> None:
    cycle = await _publish(db)
    monkeypatch.setattr(
        match_explanations_module,
        "get_settings",
        lambda: _FakeSettings("https://router.test", "fake-pem", "kid-1"),
    )

    async def _fake_execute(self, request):
        return AIRouterResponse(
            request_id="req-1",
            outcome=AIRouterOutcome.provider_unavailable,
            output=None,
            model_policy_version=None,
            trace_reference=None,
        )

    monkeypatch.setattr(match_explanations_module.AIRouterClient, "execute", _fake_execute)
    response = await client.post(f"/api/v1/scholarships/{cycle.scholarship_id}", json=PROFILE)
    assert response.status_code == 200, response.text
    assert response.json()["match_explanation"] is None


async def test_match_explanation_rate_limit_returns_a_specific_code_and_retry_after(
    db, client
) -> None:
    cycle = await _publish(db)
    from app.api.routes import MATCH_EXPLANATION_PER_MINUTE

    for _ in range(MATCH_EXPLANATION_PER_MINUTE):
        response = await client.post(
            f"/api/v1/scholarships/{cycle.scholarship_id}", json=PROFILE
        )
        assert response.status_code == 200, response.text
    response = await client.post(f"/api/v1/scholarships/{cycle.scholarship_id}", json=PROFILE)
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
    assert response.json()["code"] == "RATE_LIMIT_EXCEEDED"


async def test_unknown_scholarship_is_a_404(db, client) -> None:
    response = await client.post(
        "/api/v1/scholarships/00000000-0000-0000-0000-000000000000", json=PROFILE
    )
    assert response.status_code == 404


async def test_an_invalid_profile_field_is_a_422(db, client) -> None:
    cycle = await _publish(db)
    response = await client.post(
        f"/api/v1/scholarships/{cycle.scholarship_id}",
        json={**PROFILE, "field": "astrophysics"},
    )
    assert response.status_code == 422
