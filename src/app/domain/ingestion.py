import hashlib
from dataclasses import dataclass

from app.domain.urls import canonicalize_url


@dataclass(frozen=True)
class DiscoveryCandidate:
    normalized_url: str
    content_hash: str
    title: str
    excerpt: str | None


def prepare_candidate(url: str, title: str, excerpt: str | None) -> DiscoveryCandidate:
    normalized_url = canonicalize_url(url)
    material = "\n".join((normalized_url, title.strip(), (excerpt or "").strip()))
    content_hash = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return DiscoveryCandidate(
        normalized_url, content_hash, title.strip(), excerpt.strip() if excerpt else None
    )
