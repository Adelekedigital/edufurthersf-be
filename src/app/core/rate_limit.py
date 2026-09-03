from collections import defaultdict, deque
from time import monotonic


class InMemoryRateLimiter:
    """Development limiter; replace with a shared implementation for multi-instance production."""

    def __init__(self) -> None:
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        now = monotonic()
        bucket = self._requests[key]
        while bucket and bucket[0] <= now - window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True
