import time
from collections import defaultdict, deque


class RateLimiter:
    """Sliding-window limiter held in process memory.

    Good enough for a single-instance pilot. With more than one instance each keeps its own
    counters, so move this to Redis (or the host's edge limiter) before scaling out.
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window: float = 60.0) -> bool:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > window:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()


limiter = RateLimiter()
