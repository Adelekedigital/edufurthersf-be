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
