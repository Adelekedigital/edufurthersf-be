import time
import uuid


def new_uuid7() -> uuid.UUID:
    """Return UUIDv7 using the standard library or a compatible fallback."""
    uuid7 = getattr(uuid, "uuid7", None)
    if uuid7 is not None:
        return uuid7()
    timestamp_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    random_bits = uuid.uuid4().int
    value = (
        (timestamp_ms << 80)
        | (0x7 << 76)
        | ((random_bits >> 62) & 0xFFF) << 64
        | (0x2 << 62)
        | (random_bits & ((1 << 62) - 1))
    )
    return uuid.UUID(int=value)
