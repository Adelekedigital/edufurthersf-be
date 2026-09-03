from app.core.observability import new_request_id


def test_request_ids_are_unique_uuid_strings() -> None:
    first = new_request_id()
    second = new_request_id()
    assert first != second
    assert len(first) == 36
