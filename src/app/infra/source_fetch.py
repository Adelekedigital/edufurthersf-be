import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.domain.urls import canonicalize_url


@dataclass(frozen=True)
class FetchedSource:
    url: str
    status_code: int
    content: bytes
    content_type: str


# Shared address space (RFC 6598). CPython stopped reporting this as private
# in 3.12.4, and it is exactly where this deployment's platform proxy and
# sibling services live, so it must be excluded explicitly.
_CARRIER_GRADE_NAT = ipaddress.ip_network("100.64.0.0/10")


def _is_public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if ip.version == 4 and ip in _CARRIER_GRADE_NAT:
        return False
    # is_global still reports multicast as global, so exclude it explicitly.
    if ip.is_multicast or ip.is_unspecified:
        return False
    # Otherwise allowlist: anything not globally routable is refused, rather
    # than enumerating the non-routable ranges and missing one.
    return ip.is_global


def _is_public_host(hostname: str) -> bool:
    try:
        addresses = {str(item[4][0]) for item in socket.getaddrinfo(hostname, None)}
    except socket.gaierror as exc:
        raise ValueError("Source hostname could not be resolved") from exc
    return bool(addresses) and all(_is_public_address(address) for address in addresses)


def validate_source_url(url: str, approved_domains: list[str]) -> str:
    normalized = canonicalize_url(url)
    hostname = urlsplit(normalized).hostname or ""
    allowed = {domain.lower().lstrip(".") for domain in approved_domains}
    if not any(hostname == domain or hostname.endswith(f".{domain}") for domain in allowed):
        raise ValueError("Source URL domain is not approved")
    if not _is_public_host(hostname):
        raise ValueError("Private or reserved source host is not allowed")
    return normalized


async def fetch_source(
    url: str, approved_domains: list[str], *, max_bytes: int = 2_000_000
) -> FetchedSource:
    normalized = validate_source_url(url, approved_domains)
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=httpx.Timeout(15.0, connect=5.0),
        headers={"User-Agent": "EdufurtherScholarshipFinder/0.1"},
    ) as client:
        response = await client.get(normalized)
        if 300 <= response.status_code < 400:
            location = response.headers.get("location")
            if not location:
                raise ValueError("Redirect has no destination")
            redirected = validate_source_url(location, approved_domains)
            response = await client.get(redirected)
            normalized = redirected
        content = response.content
        if len(content) > max_bytes:
            raise ValueError("Source response exceeds maximum size")
        return FetchedSource(
            normalized, response.status_code, content, response.headers.get("content-type", "")
        )
