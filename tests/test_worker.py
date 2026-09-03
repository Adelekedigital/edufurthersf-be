import inspect

from app.infra.worker import execute_job


def test_worker_entrypoint_is_async() -> None:
    assert callable(execute_job)
    assert inspect.iscoroutinefunction(execute_job)
