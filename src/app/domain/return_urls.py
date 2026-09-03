from urllib.parse import urlsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}


def _port(scheme: str, port: int | None) -> int | None:
    return port if port is not None else _DEFAULT_PORTS.get(scheme)


def is_allowed_return_url(candidate: str, allowed_prefix: str) -> bool:
    """Compare a return URL to the allowed prefix structurally, not lexically.

    A plain ``startswith`` is not an origin check: with a prefix of
    ``https://app.example.com`` it also accepts
    ``https://app.example.com.attacker.test/`` and
    ``https://app.example.com@attacker.test/``. The handoff token travels to
    whatever host wins this comparison, so it is matched on scheme, host, port
    and a path boundary.
    """
    if not allowed_prefix:
        return False
    allowed = urlsplit(allowed_prefix)
    target = urlsplit(candidate)
    allowed_scheme = allowed.scheme.lower()
    if allowed_scheme not in _DEFAULT_PORTS or target.scheme.lower() != allowed_scheme:
        return False
    # Credentials in the authority let the real host hide after an "@".
    if target.username or target.password:
        return False
    if (target.hostname or "").lower() != (allowed.hostname or "").lower():
        return False
    if not target.hostname:
        return False
    if _port(allowed_scheme, target.port) != _port(allowed_scheme, allowed.port):
        return False
    allowed_path = allowed.path or "/"
    if not allowed_path.endswith("/"):
        allowed_path += "/"
    target_path = target.path or "/"
    if not target_path.endswith("/"):
        target_path += "/"
    return target_path.startswith(allowed_path)
