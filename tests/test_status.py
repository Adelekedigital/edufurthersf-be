from datetime import UTC, datetime, timedelta

from app.domain.models import PublicStatus
from app.domain.status import evaluate_public_status


def test_expired_deadline_downgrades_open_status() -> None:
    now = datetime.now(UTC)
    assert (
        evaluate_public_status(
            PublicStatus.open_verified,
            deadline_at=now - timedelta(seconds=1),
            status_valid_until=now + timedelta(days=1),
            now=now,
        )
        == PublicStatus.status_unknown
    )


def test_fresh_open_status_remains_open() -> None:
    now = datetime.now(UTC)
    assert (
        evaluate_public_status(
            PublicStatus.open_verified,
            deadline_at=now + timedelta(days=1),
            status_valid_until=now + timedelta(days=1),
            now=now,
        )
        == PublicStatus.open_verified
    )
