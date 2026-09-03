from app.infra.sessions import record_search


def test_search_module_exports_persistence_helper() -> None:
    assert callable(record_search)
