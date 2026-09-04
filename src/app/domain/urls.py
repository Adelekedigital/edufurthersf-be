from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def normalize_domain(value: str) -> str:
    """Normalize a bare approved-domain entry: lowercase, no leading dot.

    Shared by Source and Provider admin creation, both of which store a list
    of domains a fetch or an official-URL claim is checked against.
    """
    domain = value.strip().lower().lstrip(".")
    if not domain:
        raise ValueError("Domain must not be blank")
    return domain


def canonicalize_url(value: str) -> str:
    """Normalize an HTTP(S) URL for identity; tracking parameters are discarded."""
    parts = urlsplit(value.strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        raise ValueError("Only absolute HTTP(S) URLs are allowed")
    host = parts.hostname.lower() if parts.hostname else ""
    port = parts.port
    netloc = host
    if port and not (
        (parts.scheme.lower() == "http" and port == 80)
        or (parts.scheme.lower() == "https" and port == 443)
    ):
        netloc = f"{host}:{port}"
    query = [
        (key, val)
        for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}
    ]
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), netloc, path, urlencode(query), ""))
