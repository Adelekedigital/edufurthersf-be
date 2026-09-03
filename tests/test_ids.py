from app.core.ids import new_uuid7


def test_new_ids_are_uuidv7() -> None:
    value = new_uuid7()
    assert value.version == 7
    assert value.bytes[8] & 0xC0 == 0x80
