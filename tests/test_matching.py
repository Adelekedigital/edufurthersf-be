from app.domain.matching import SearchProfile, evaluate_match


def profile() -> SearchProfile:
    return SearchProfile(
        "NG",
        frozenset({"CA", "GB"}),
        frozenset({"masters"}),
        frozenset({"health_and_medical_sciences"}),
    )


def test_confirmed_match() -> None:
    decision = evaluate_match(
        profile(),
        {
            "destinations": ["CA"],
            "levels": ["masters"],
            "origin_mode": "restricted",
            "origins": ["NG"],
            "field_mode": "restricted",
            "fields": ["health_and_medical_sciences"],
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
            "fields": ["health_and_medical_sciences"],
        },
    )
    assert decision is not None
    assert decision.fit == "possible"
    assert decision.caveats


def test_multiple_requested_degrees_match_any_accepted_degree() -> None:
    multi = SearchProfile("NG", frozenset({"CA"}), frozenset({"masters", "mba"}), None)
    assert (
        evaluate_match(
            multi,
            {"destinations": ["CA"], "levels": ["mba"], "origin_mode": "unrestricted"},
        )
        is not None
    )


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
    no_field_profile = SearchProfile("NG", frozenset({"CA"}), frozenset({"masters"}), None)
    decision = evaluate_match(
        no_field_profile,
        {
            "destinations": ["CA"],
            "levels": ["masters"],
            "origin_mode": "unrestricted",
            "field_mode": "restricted",
            "fields": ["technology"],
        },
    )
    assert decision is not None
    assert "field_compatible" not in decision.reason_codes


def test_explicit_null_facts_values_degrade_to_no_match_not_a_crash() -> None:
    assert (
        evaluate_match(
            profile(),
            {
                "destinations": None,
                "levels": None,
                "origin_mode": None,
                "origins": None,
                "field_mode": None,
                "fields": None,
            },
        )
        is None
    )


def test_field_outside_the_searched_bucket_is_excluded() -> None:
    ict_profile = SearchProfile(
        "NG", frozenset({"CA"}), frozenset({"masters"}), frozenset({"technology"})
    )
    assert (
        evaluate_match(
            ict_profile,
            {
                "destinations": ["CA"],
                "levels": ["masters"],
                "origin_mode": "unrestricted",
                "field_mode": "restricted",
                "fields": ["law"],
            },
        )
        is None
    )


def test_legacy_field_values_are_normalized_during_transition() -> None:
    assert (
        evaluate_match(
            profile(),
            {
                "destinations": ["CA"],
                "levels": ["masters"],
                "origin_mode": "unrestricted",
                "field_mode": "restricted",
                "fields": ["health"],
            },
        )
        is not None
    )
