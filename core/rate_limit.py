"""In-memory sliding-window rate limiter.

Used for the public card endpoints (per IP). It lives in the process: with
several workers each one keeps its own count, which is enough to stop abuse of a
single instance. Behind a proxy the IP is the forwarded one (`--proxy-headers`
in docker/entrypoint.sh).
"""

import math
import threading
import time
from collections import deque

# Above this many keys, stale ones are dropped on the next hit.
MAX_KEYS = 10_000


class SlidingWindowLimiter:
    def __init__(self, window_seconds: float = 60) -> None:
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int) -> int | None:
        """Count one request. Returns the seconds to wait if `key` is over `limit`."""
        now = time.monotonic()
        start = now - self.window_seconds
        with self._lock:
            if len(self._hits) > MAX_KEYS:
                self._drop_stale(start)
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= start:
                hits.popleft()
            if len(hits) >= limit:
                return max(1, math.ceil(hits[0] - start))
            hits.append(now)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def _drop_stale(self, start: float) -> None:
        for key in [key for key, hits in self._hits.items() if not hits or hits[-1] <= start]:
            del self._hits[key]
