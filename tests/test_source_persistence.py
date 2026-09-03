import inspect

from app.infra.source_persistence import fetch_and_persist_page


def test_source_persistence_entrypoint_is_async() -> None:
    assert inspect.iscoroutinefunction(fetch_and_persist_page)
