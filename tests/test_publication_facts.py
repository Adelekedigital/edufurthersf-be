"""build_cycle_facts: validating a cycle's facts, including the deadline's
precision and timezone metadata the data standard's §7 requires."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.domain.countries import CountryVocabulary
from app.domain.publication import build_cycle_facts

COUNTRIES = CountryVocabulary(
    names={"NG": "Nigeria", "US": "United States"}, destinations=frozenset({"US"})
)


def _facts(**overrides):
    base = dict(
        destinations=["US"],
        levels=["masters"],
        origin_mode="unrestricted",
        origins=[],
        field_mode="unknown",
        fields=[],
        evidence_fresh=True,
        deadline_at=None,
        countries=COUNTRIES,
    )
    base.update(overrides)
    return build_cycle_facts(**base)


def test_deadline_precision_defaults_to_date() -> None:
    facts = _facts(deadline_at=datetime(2026, 6, 30))
    assert facts["deadline_precision"] == "date"
    assert "deadline_timezone" not in facts


def test_a_known_timezone_is_stored_alongside_the_deadline() -> None:
    facts = _facts(deadline_at=datetime(2026, 6, 30), deadline_timezone="America/New_York")
    assert facts["deadline_timezone"] == "America/New_York"


def test_an_unrecognised_timezone_is_refused_at_publish_time() -> None:
    """Refused here, not silently accepted and only discovered as a no-op
    fail-closed cutoff later when the record is actually read."""
    with pytest.raises(ValueError, match="Unknown deadline_timezone"):
        _facts(deadline_at=datetime(2026, 6, 30), deadline_timezone="Not/AZone")


def test_no_deadline_means_no_precision_or_timezone_keys_at_all() -> None:
    facts = _facts(deadline_at=None)
    assert "deadline_at" not in facts
    assert "deadline_precision" not in facts
    assert "deadline_timezone" not in facts


def test_datetime_precision_can_be_requested_explicitly() -> None:
    facts = _facts(deadline_at=datetime(2026, 6, 30, 12, 0), deadline_precision="datetime")
    assert facts["deadline_precision"] == "datetime"


def test_expected_reopen_month_is_stored_when_given() -> None:
    facts = _facts(expected_reopen_month=6)
    assert facts["expected_reopen_month"] == 6


def test_no_expected_reopen_month_means_no_key_at_all() -> None:
    """Absent, not null or guessed - the same honesty rule as origin_mode:
    only a reviewer's real evidence of roughly when a scheme reopens belongs
    here, never a default."""
    facts = _facts()
    assert "expected_reopen_month" not in facts


def test_field_names_are_stored_verbatim_deduped_and_sorted() -> None:
    facts = _facts(field_names=["Mathematics", "mathematics", "Mathematics", "Statistics"])
    assert facts["field_names"] == ["Mathematics", "Statistics", "mathematics"]


def test_no_field_names_means_no_key_at_all() -> None:
    """Same honesty rule as eligibility_note/expected_reopen_month - absent
    when nothing was actually given, never an empty list stored anyway."""
    facts = _facts()
    assert "field_names" not in facts
    assert _facts(field_names=[])
    assert "field_names" not in _facts(field_names=["", "  "])
