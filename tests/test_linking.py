from app.domain.linking import LinkOutcome, decide_link


def test_single_candidate_links() -> None:
    decision = decide_link(["one"])
    assert decision.outcome == LinkOutcome.linked


def test_multiple_candidates_require_review() -> None:
    decision = decide_link(["one", "two"])
    assert decision.outcome == LinkOutcome.needs_review


def test_no_candidate_creates_new_candidate() -> None:
    assert decide_link([]).outcome == LinkOutcome.new_candidate
