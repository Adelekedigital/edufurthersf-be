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


def _is_public_host(hostname: str) -> bool:
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, None)}
    except socket.gaierror as exc:
        raise ValueError("Source hostname could not be resolved") from exc
    return all(
        not (ip := ipaddress.ip_address(address)).is_private
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_reserved
        for address in addresses
    )


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
