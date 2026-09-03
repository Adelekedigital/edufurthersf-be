from unittest.mock import patch

import pytest

from app.infra.source_fetch import validate_source_url


def test_source_url_requires_approved_domain() -> None:
    with pytest.raises(ValueError):
        validate_source_url("https://example.org/award", ["official.edu"])


@patch(
    "app.infra.source_fetch.socket.getaddrinfo",
    return_value=[(None, None, None, None, ("93.184.216.34", 0))],
)
def test_source_url_accepts_approved_public_domain(_resolver) -> None:
    assert (
        validate_source_url("https://official.edu/award#section", ["official.edu"])
        == "https://official.edu/award"
    )
