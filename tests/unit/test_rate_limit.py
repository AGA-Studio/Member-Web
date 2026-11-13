"""core/rate_limit.py: the in-memory sliding window of the public card endpoints."""

import time

from core import rate_limit
from core.rate_limit import SlidingWindowLimiter


def test_allows_up_to_the_limit() -> None:
    limiter = SlidingWindowLimiter(window_seconds=60)
    assert [limiter.hit("ip", 3) for _ in range(3)] == [None, None, None]
    wait = limiter.hit("ip", 3)
    assert wait is not None and 1 <= wait <= 60


def test_keys_are_counted_apart() -> None:
    limiter = SlidingWindowLimiter(window_seconds=60)
    assert limiter.hit("a", 1) is None
    assert limiter.hit("b", 1) is None
    assert limiter.hit("a", 1) is not None


def test_old_hits_leave_the_window() -> None:
    limiter = SlidingWindowLimiter(window_seconds=0.05)
    assert limiter.hit("ip", 1) is None
    time.sleep(0.06)
    assert limiter.hit("ip", 1) is None


def test_reset_forgets_everything() -> None:
    limiter = SlidingWindowLimiter(window_seconds=60)
    limiter.hit("ip", 1)
    limiter.reset()
    assert limiter.hit("ip", 1) is None


def test_stale_keys_are_dropped(monkeypatch) -> None:
    monkeypatch.setattr(rate_limit, "MAX_KEYS", 2)
    limiter = SlidingWindowLimiter(window_seconds=0.05)
    for key in ("a", "b", "c"):
        limiter.hit(key, 1)
    time.sleep(0.06)
    limiter.hit("d", 1)
    assert set(limiter._hits) == {"d"}
