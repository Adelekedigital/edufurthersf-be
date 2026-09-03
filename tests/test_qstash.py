from app.infra.qstash import QStashVerificationConfig, QStashVerifier


def test_qstash_verifier_fails_closed_when_unconfigured() -> None:
    verifier = QStashVerifier(QStashVerificationConfig(None, None, "https://finder/jobs"))
    assert not verifier.verify(
        raw_body=b"{}", signature="anything", destination="https://finder/jobs"
    )
