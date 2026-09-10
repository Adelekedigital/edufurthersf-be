"""Unit tests for `_derive_facts` and `_normalised_set`: `facts` JSONB isn't
schema-enforced below `publish()` (and, as of migration
`0020_facts_contract_constraints`, below that too - but that migration only
covers what's actually written through a real commit). These call the
sanitizers directly with hand-built dicts rather than getting bad data into
a real Postgres row: once migration 0020 exists, most of these scenarios
can no longer be produced through a normal `db.commit()`, so the DB
integration tests that used to simulate "a row already got corrupted" were
testing Postgres's rejection behavior instead of the sanitizer's
degrade-gracefully behavior they exist to verify.
"""

from __future__ import annotations

from app.domain.facts import derive_facts as _derive_facts
from app.domain.matching import _normalised_set

BASE_FACTS = {
    "destinations": ["CA"],
    "levels": ["masters"],
    "origin_mode": "unrestricted",
    "field_mode": "restricted",
    "fields": ["health_and_medical_sciences"],
    "evidence_fresh": True,
}


def test_out_of_contract_facts_degrade_individually_not_all_at_once() -> None:
    """`deadline_precision` clamps to "datetime" rather than going null -
    the same fallback already used when the key is simply absent - because
    `deadline_at` itself is still a real, valid instant here; nulling
    `deadline_precision` while leaving `deadline_at` set would violate the
    documented "null iff deadline_at is null" invariant. Every other
    out-of-contract value here degrades to its own safe default
    independently - one bad field never affects another."""
    derived = _derive_facts(
        {
            **BASE_FACTS,
            "deadline_at": "2026-12-31T00:00:00Z",
            "deadline_precision": "fortnight",
            "expected_reopen_month": 13,
            "levels": ["masters", 123, None],
            "funding_type": "free_money",
            "eligibility_note": 12345,
            "programme_names": ["MSc Development Economics", 42, None],
        }
    )
    assert derived.deadline_at is not None
    assert derived.deadline_at.isoformat().startswith("2026-12-31")
    assert derived.deadline_precision == "datetime"
    assert derived.public_deadline_precision == "datetime"
    assert derived.expected_reopen_month is None
    assert derived.degree_levels == ["masters"]
    assert derived.funding_type is None
    assert derived.eligibility_note is None
    assert derived.field_names == ["Health and Medical Sciences"]
    assert derived.programme_names == ["MSc Development Economics"]


def test_an_unhashable_funding_type_does_not_crash_the_membership_check() -> None:
    """`raw_value in TAXONOMY.funding_types` raises TypeError instead of
    returning False when raw_value is unhashable (a list/dict) - the
    isinstance check must run first."""
    derived = _derive_facts({**BASE_FACTS, "funding_type": ["fully_funded"]})
    assert derived.funding_type is None


def test_a_non_list_levels_or_programme_names_does_not_crash() -> None:
    """A bare `for x in value` over a non-list raises TypeError - `levels`/
    `programme_names` must degrade to empty, not crash, when facts holds
    something other than a list at all (not just a list with bad items)."""
    derived = _derive_facts(
        {**BASE_FACTS, "levels": "masters", "programme_names": "MSc Development Economics"}
    )
    assert derived.degree_levels == []
    assert derived.programme_names == []
    assert derived.field_names == ["Health and Medical Sciences"]


def test_unhashable_enum_values_do_not_crash_fact_derivation() -> None:
    derived = _derive_facts(
        {
            **BASE_FACTS,
            "deadline_precision": [],
            "origin_mode": {},
            "field_mode": [],
        }
    )
    assert derived.deadline_precision == "datetime"
    assert derived.origin_mode == "unknown"
    assert derived.field_mode == "unknown"


def test_a_boolean_reopen_month_is_not_treated_as_month_one() -> None:
    """`isinstance(True, int)` is True in Python - a stray boolean in facts
    must not slip through the month-range guard and get coerced to 1."""
    derived = _derive_facts({**BASE_FACTS, "expected_reopen_month": True})
    assert derived.expected_reopen_month is None


def test_funding_type_read_uses_the_same_normalization_as_publish() -> None:
    """A value that would validate at publish time (`TAXONOMY.funding_type()`
    strips/lowercases before checking) must not silently read back as null
    just because a row written outside `publish()` didn't normalize it
    first - the read side has to apply the exact same rule, not a
    stricter one."""
    derived = _derive_facts({**BASE_FACTS, "funding_type": " Fully_Funded "})
    assert derived.funding_type == "fully_funded"


def test_sanitized_dict_never_shows_a_value_that_disagrees_with_the_typed_fields() -> None:
    """`ScholarshipDetailResponse.facts` is built from this property instead
    of the raw stored dict - it must never show a garbage value the typed
    fields above have already cleaned up, and must omit (not null) a key
    `build_cycle_facts` itself would have omitted."""
    derived = _derive_facts(
        {
            **BASE_FACTS,
            "deadline_at": "2026-12-31T00:00:00Z",
            "deadline_precision": "fortnight",
            "funding_type": "not_a_real_type",
        }
    )
    sanitized = derived.sanitized_dict
    assert sanitized["deadline_precision"] == "datetime"
    assert "funding_type" not in sanitized
    assert sanitized["destinations"] == ["CA"]


def test_explicit_null_facts_values_do_not_crash_normalised_set() -> None:
    """`facts.get(key, [])` only substitutes the default when the key is
    absent, not when it's present but explicitly null - a bare `for v in
    None` used to raise TypeError here, in the per-row hard-gate loop every
    `/search` request runs, over the value of a single key."""
    assert _normalised_set({"destinations": None}, "destinations") == set()
    assert _normalised_set({}, "destinations") == set()
    assert _normalised_set({"destinations": ["CA", "gb"]}, "destinations") == {"ca", "gb"}


def test_an_empty_eligibility_note_is_treated_as_absent() -> None:
    """build_cycle_facts only ever writes this key for a non-empty note - a
    bare isinstance(str) check would let "" through, a shape
    build_cycle_facts can never actually produce."""
    derived = _derive_facts({**BASE_FACTS, "eligibility_note": ""})
    assert derived.eligibility_note is None
    assert "eligibility_note" not in derived.sanitized_dict


def test_a_non_string_deadline_timezone_does_not_crash_status_evaluation() -> None:
    """A non-string deadline_timezone reaching ZoneInfo(...) unguarded
    raises TypeError, not the ZoneInfoNotFoundError deadline_cutoff
    actually catches - deadline_timezone must be sanitized before it ever
    reaches that call, the same as every other facts-derived value."""
    derived = _derive_facts(
        {
            **BASE_FACTS,
            "deadline_at": "2026-12-31T00:00:00Z",
            "deadline_timezone": ["not", "a", "string"],
        }
    )
    assert derived.deadline_timezone is None


def test_programme_names_does_not_leak_canonical_field_labels() -> None:
    """A cycle that sets `fields` but never explicitly sets `programme_names`
    must not have the auto-generated canonical `field_names` label leak into
    `programme_names` as though it were free-text programme wording -
    build_cycle_facts always writes a canonical `field_names` key whenever
    `fields` is given."""
    derived = _derive_facts({**BASE_FACTS, "field_names": ["Health and Medical Sciences"]})
    assert derived.programme_names == []


def test_duplicate_field_aliases_do_not_produce_duplicate_canonical_fields() -> None:
    """`fields=["ict", "cs"]` both alias to "technology" - `fields` must
    dedupe the same way `field_names` already does, or a frontend zipping
    the two arrays by index misrenders."""
    derived = _derive_facts({**BASE_FACTS, "fields": ["ict", "cs"]})
    assert derived.fields == ["technology"]
    assert derived.field_names == ["Technology"]


def test_duplicate_degree_aliases_do_not_produce_duplicate_degree_levels() -> None:
    derived = _derive_facts({**BASE_FACTS, "levels": ["phd", "doctorate"]})
    assert derived.degree_levels == ["doctorate"]
