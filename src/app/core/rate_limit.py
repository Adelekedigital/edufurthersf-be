from collections import defaultdict, deque
from time import monotonic


class InMemoryRateLimiter:
    """Development limiter; replace with a shared implementation for multi-instance production."""

    def __init__(self) -> None:
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._next_sweep = 0.0

    def allow(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        now = monotonic()
        self._evict_expired(now, window_seconds)
        bucket = self._requests[key]
        while bucket and bucket[0] <= now - window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True

    def _evict_expired(self, now: float, window_seconds: int) -> None:
        """Drop buckets whose window has fully elapsed.

        Trimming only the bucket being served leaves one dict entry per key
        forever, so a caller varying its key grows the map without bound.
        """
        if now < self._next_sweep:
            return
        self._next_sweep = now + window_seconds
        cutoff = now - window_seconds
        for key in [k for k, b in self._requests.items() if not b or b[-1] <= cutoff]:
            del self._requests[key]
