"""The domain port's shape matches the standard's documented contract - a
drifted constant here would silently violate a policy nothing else checks."""

from __future__ import annotations

from app.domain.ai_router import (
    DEFAULT_TIMEOUT_SECONDS,
    MAX_PROVIDER_ATTEMPTS,
    AIRouterOutcome,
    AIRouterRequest,
    AITask,
)


def test_only_the_standards_two_tasks_are_allowlisted() -> None:
    assert {task.value for task in AITask} == {"scholarship_extraction", "match_explanation"}


def test_the_standards_v1_policy_numbers_are_encoded_exactly() -> None:
    assert DEFAULT_TIMEOUT_SECONDS == 45
    assert MAX_PROVIDER_ATTEMPTS == 2


def test_a_request_never_names_a_model_or_provider() -> None:
    """Model IDs and provider keys are router-side policy, not a caller's
    concern - encoded by the request shape simply having nowhere to put one."""
    request = AIRouterRequest(
        task=AITask.scholarship_extraction,
        task_version="v1",
        schema_version=1,
        product_id="scholarship_finder",
        feature_id="review_draft",
        correlation_id="corr-1",
        idempotency_key="idem-1",
        source_data={"raw_title": "Award A"},
    )
    assert not hasattr(request, "model")
    assert not hasattr(request, "provider")


def test_optional_journey_context_defaults_to_absent_not_fabricated() -> None:
    request = AIRouterRequest(
        task=AITask.match_explanation,
        task_version="v1",
        schema_version=1,
        product_id="scholarship_finder",
        feature_id="search",
        correlation_id="corr-2",
        idempotency_key="idem-2",
        source_data={},
    )
    assert request.journey_id is None
    assert request.session_id is None
    assert request.handoff_id is None


def test_outcome_never_includes_a_publish_or_verify_state() -> None:
    """The router "cannot set published or verified state" - there is no
    outcome value that could be mistaken for one."""
    assert AIRouterOutcome.__members__.keys() == {
        "completed",
        "invalid_schema",
        "budget_exhausted",
        "provider_unavailable",
    }
