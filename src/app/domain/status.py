from datetime import UTC, datetime

from app.domain.models import PublicStatus


def evaluate_public_status(
    stored_status: PublicStatus,
    *,
    deadline_at: datetime | None,
    status_valid_until: datetime | None,
    now: datetime | None = None,
) -> PublicStatus:
    """Re-evaluate time-sensitive status on read; never keep an expired Open now result."""
    current = now or datetime.now(UTC)
    if stored_status == PublicStatus.open_verified:
        if deadline_at and deadline_at <= current:
            return PublicStatus.status_unknown
        if status_valid_until and status_valid_until <= current:
            return PublicStatus.status_unknown
    return stored_status
