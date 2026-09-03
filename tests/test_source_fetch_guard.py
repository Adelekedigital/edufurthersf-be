"""The outbound fetch guard is the SSRF boundary for the crawler."""

from __future__ import annotations

import pytest

from app.infra.source_fetch import _is_public_address, validate_source_url

APPROVED = ["example.test"]


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",  # loopback
        "10.0.0.5",  # RFC 1918
        "192.168.1.1",
        "172.16.0.1",
        "169.254.169.254",  # cloud instance metadata
        "100.64.0.4",  # RFC 6598, the platform proxy's own network
        "100.127.255.254",
        "224.0.0.1",  # multicast
        "0.0.0.0",  # unspecified
        "::1",
        "fd00::1",  # unique local
    ],
)
def test_non_routable_addresses_are_refused(address: str) -> None:
    assert _is_public_address(address) is False


@pytest.mark.parametrize(
    "address", ["93.184.216.34", "8.8.8.8", "2606:2800:220:1:248:1893:25c8:1946"]
)
def test_globally_routable_addresses_are_allowed(address: str) -> None:
    assert _is_public_address(address) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://attacker.test/page",
        "https://example.test.attacker.test/page",
        "https://notexample.test/page",
    ],
)
def test_urls_outside_the_approved_domains_are_refused(url: str) -> None:
    with pytest.raises(ValueError, match="not approved"):
        validate_source_url(url, APPROVED)


def test_subdomains_of_an_approved_domain_are_allowed(monkeypatch) -> None:
    monkeypatch.setattr("app.infra.source_fetch._is_public_host", lambda hostname: True)
    assert validate_source_url("https://awards.example.test/page", APPROVED).startswith(
        "https://awards.example.test/page"
    )


def test_a_private_approved_host_is_still_refused(monkeypatch) -> None:
    """Domain approval must not override the network guard."""
    monkeypatch.setattr("app.infra.source_fetch._is_public_host", lambda hostname: False)
    with pytest.raises(ValueError, match="Private or reserved"):
        validate_source_url("https://example.test/page", APPROVED)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.test/x", "//example.test/x"])
def test_non_http_schemes_are_refused(url: str) -> None:
    with pytest.raises(ValueError):
        validate_source_url(url, APPROVED)
