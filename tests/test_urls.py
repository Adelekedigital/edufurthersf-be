import pytest

from app.domain.urls import canonicalize_url


def test_canonicalize_url_removes_tracking_and_fragment() -> None:
    assert (
        canonicalize_url("HTTPS://Example.ORG/app/?utm_source=x&view=full#section")
        == "https://example.org/app?view=full"
    )


def test_canonicalize_url_rejects_non_http() -> None:
    with pytest.raises(ValueError):
        canonicalize_url("javascript:alert(1)")
