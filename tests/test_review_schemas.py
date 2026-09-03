import pytest
from pydantic import ValidationError

from app.api.review_schemas import ReviewDecisionRequest


def test_approval_requires_valid_slug_format() -> None:
    with pytest.raises(ValidationError):
        ReviewDecisionRequest(decision="approve", reason="approved", slug="Not Valid")


def test_rejection_only_requires_reason() -> None:
    request = ReviewDecisionRequest(decision="reject", reason="Not an official source")
    assert request.decision == "reject"
