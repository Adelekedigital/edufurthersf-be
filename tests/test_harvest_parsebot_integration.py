"""The app-level kill switch: harvest_parsebot must not touch the network at
all when neither Source is registered/active, not just discard the result."""

from __future__ import annotations

import pytest

from app.infra.worker import _harvest_parsebot
from tests.conftest import requires_db


@requires_db
@pytest.mark.anyio
async def test_harvest_is_a_no_op_with_no_active_source(db) -> None:
    # No ScholarshipPortal/PhDScanner Source registered in this clean test
    # database - _harvest_parsebot must return cleanly without ever
    # constructing a Parse SDK client (which would require PARSE_API_KEY and
    # a real network call neither is available in this suite).
    await _harvest_parsebot(db)
