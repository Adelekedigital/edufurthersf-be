from app.domain.ingestion import prepare_candidate


def test_prepare_candidate_is_stable_and_canonical() -> None:
    candidate = prepare_candidate(
        "https://Example.org/app/?utm_source=feed#x", "  Award  ", "  excerpt  "
    )
    assert candidate.normalized_url == "https://example.org/app"
    assert candidate.title == "Award"
    assert candidate.excerpt == "excerpt"
    assert len(candidate.content_hash) == 64
