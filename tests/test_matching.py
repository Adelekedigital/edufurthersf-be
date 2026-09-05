from app.domain.matching import SearchProfile, evaluate_match


def profile() -> SearchProfile:
    return SearchProfile("NG", frozenset({"CA", "GB"}), "masters", "public_health")


def test_confirmed_match() -> None:
    decision = evaluate_match(
        profile(),
        {
            "destinations": ["CA"],
            "levels": ["masters"],
            "origin_mode": "restricted",
            "origins": ["NG"],
            "field_mode": "restricted",
            "fields": ["public_health"],
            "evidence_fresh": True,
        },
    )
    assert decision is not None
    assert decision.fit == "confirmed"
    assert decision.score == 50


def test_unknown_eligibility_is_possible_not_confirmed() -> None:
    decision = evaluate_match(
        profile(),
        {
            "destinations": ["GB"],
            "levels": ["masters"],
            "origin_mode": "unknown",
            "field_mode": "restricted",
            "fields": ["public_health"],
        },
    )
    assert decision is not None
    assert decision.fit == "possible"
    assert decision.caveats


def test_destination_is_a_hard_gate() -> None:
    assert (
        evaluate_match(
            profile(),
            {
                "destinations": ["US"],
                "levels": ["masters"],
                "origin_mode": "unrestricted",
                "field_mode": "all",
            },
        )
        is None
    )


def test_no_field_preference_never_excludes_a_field_restricted_record() -> None:
    """A searcher with no field preference (e.g. their real field - Law,
    Business - isn't one of the two taxonomy codes) must still see every
    destination/level/origin-eligible record, not just field_mode="all" ones."""
    no_field_profile = SearchProfile("NG", frozenset({"CA"}), "masters", None)
    decision = evaluate_match(
        no_field_profile,
        {
            "destinations": ["CA"],
            "levels": ["masters"],
            "origin_mode": "unrestricted",
            "field_mode": "restricted",
            "fields": ["computer_science"],
        },
    )
    assert decision is not None
    assert "field_compatible" not in decision.reason_codes
