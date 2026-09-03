from app.infra.sessions import filter_digest, record_search_response


def test_search_module_exports_persistence_helpers() -> None:
    assert callable(record_search_response)


def test_filter_digest_is_order_independent() -> None:
    """The digest binds a cursor to its query, so key order must not change it."""
    assert filter_digest({"a": 1, "b": 2}) == filter_digest({"b": 2, "a": 1})
    assert filter_digest({"a": 1}) != filter_digest({"a": 2})
