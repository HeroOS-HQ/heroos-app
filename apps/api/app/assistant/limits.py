"""A per-tester request limit for the Hannah demo (in this API process).

It protects the provider's free-tier quota from one runaway browser tab; it is
not a security boundary (the tester allowlist is). Keys are identity subjects
held in memory only, never logged.
"""

import threading
import time
from collections import deque
from collections.abc import Callable

# Each tester: at most this many messages in any window.
TESTER_LIMIT = 20
TESTER_WINDOW_SECONDS = 300.0


class SlidingWindowLimiter:
    def __init__(
        self,
        limit: int = TESTER_LIMIT,
        window_seconds: float = TESTER_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}

    def acquire(self, key: str) -> int | None:
        """Record one request; None if allowed, else the seconds until one is."""
        now = self._clock()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self._window:
                hits.popleft()
            if len(hits) >= self._limit:
                return max(1, int(hits[0] + self._window - now) + 1)
            hits.append(now)
            return None
