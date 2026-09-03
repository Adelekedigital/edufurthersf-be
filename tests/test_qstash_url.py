from app.infra.qstash import publish_url


def test_qstash_publish_url_uses_configured_region() -> None:
    assert (
        publish_url("https://qstash-us-east-1.upstash.io/")
        == "https://qstash-us-east-1.upstash.io/v2/publish"
    )
