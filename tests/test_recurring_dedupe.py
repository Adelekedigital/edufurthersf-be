"""A QStash *schedule* redelivers one static body forever; ProcessingJob's
dedupe_key is permanently unique, so a recurring job kind must compute its
own key server-side rather than trust whatever the static body carries -
otherwise only the first-ever delivery would run."""

from __future__ import annotations

from app.api.routes import RECURRING_WEEKLY_KINDS, _weekly_dedupe_key


def test_harvest_parsebot_is_a_recurring_weekly_kind() -> None:
    assert "harvest_parsebot" in RECURRING_WEEKLY_KINDS


def test_weekly_dedupe_key_is_stable_within_the_same_call() -> None:
    first = _weekly_dedupe_key("harvest_parsebot")
    second = _weekly_dedupe_key("harvest_parsebot")
    assert first == second
    assert first.startswith("harvest_parsebot:")


def test_weekly_dedupe_key_differs_by_kind() -> None:
    assert _weekly_dedupe_key("harvest_parsebot") != _weekly_dedupe_key("other_kind")
