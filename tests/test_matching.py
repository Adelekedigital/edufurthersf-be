from app.domain.matching import SearchProfile, evaluate_match


def profile() -> SearchProfile:
    #: A search for the broad "health_and_welfare" field, already expanded to
    #: its narrow children by `taxonomy.normalize_search_filters`.
    return SearchProfile("NG", frozenset({"CA", "GB"}), "masters", frozenset({"health", "welfare"}))


def test_confirmed_match() -> None:
    decision = evaluate_match(
        profile(),
        {
            "destinations": ["CA"],
            "levels": ["masters"],
            "origin_mode": "restricted",
            "origins": ["NG"],
            "field_mode": "restricted",
            "fields": ["health"],
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
            "fields": ["health"],
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
    """A searcher with no field preference must still see every
    destination/level/origin-eligible record, not just field_mode="all" ones."""
    no_field_profile = SearchProfile("NG", frozenset({"CA"}), "masters", None)
    decision = evaluate_match(
        no_field_profile,
        {
            "destinations": ["CA"],
            "levels": ["masters"],
            "origin_mode": "unrestricted",
            "field_mode": "restricted",
            "fields": ["ict"],
        },
    )
    assert decision is not None
    assert "field_compatible" not in decision.reason_codes


def test_a_narrow_tag_outside_the_searched_broad_bucket_is_excluded() -> None:
    """Searching the broad "ict" field must not match a scholarship tagged
    with a narrow field from an unrelated broad bucket."""
    ict_profile = SearchProfile("NG", frozenset({"CA"}), "masters", frozenset({"ict"}))
    decision = evaluate_match(
        ict_profile,
        {
            "destinations": ["CA"],
            "levels": ["masters"],
            "origin_mode": "unrestricted",
            "field_mode": "restricted",
            "fields": ["law"],
        },
    )
    assert decision is None
