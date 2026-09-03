from types import SimpleNamespace

from app.api.routes import _qstash_destination
from app.core.config import get_settings

PUBLIC = "https://api.example.com/api/v1/internal/jobs"


def _request(url: str) -> SimpleNamespace:
    return SimpleNamespace(url=url)


def _with_destination(monkeypatch, value: str) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "qstash_expected_destination", value, raising=False)


def test_configured_destination_wins_over_the_proxied_request_url(monkeypatch) -> None:
    _with_destination(monkeypatch, PUBLIC)
    proxied = _request("http://app.internal:8000/api/v1/internal/jobs")
    assert _qstash_destination(proxied) == PUBLIC


def test_compatibility_route_appends_the_job_kind(monkeypatch) -> None:
    _with_destination(monkeypatch, PUBLIC)
    proxied = _request("http://app.internal:8000/api/v1/internal/jobs/import_feed")
    assert _qstash_destination(proxied, "import_feed") == f"{PUBLIC}/import_feed"


def test_unconfigured_destination_falls_back_to_the_request_url(monkeypatch) -> None:
    _with_destination(monkeypatch, "")
    local = _request("http://localhost:8000/api/v1/internal/jobs")
    assert _qstash_destination(local) == "http://localhost:8000/api/v1/internal/jobs"
    assert _qstash_destination(local, "import_feed") == "http://localhost:8000/api/v1/internal/jobs"
