from app.core.sentry import scrub_event


def test_sentry_scrubber_removes_secrets_and_emails() -> None:
    event = {
        "message": "Contact user@example.com",
        "request": {"headers": {"Authorization": "secret"}},
    }
    scrubbed = scrub_event(event)
    assert "user@example.com" not in str(scrubbed)
    assert scrubbed["request"]["headers"]["Authorization"] == "[Filtered]"
