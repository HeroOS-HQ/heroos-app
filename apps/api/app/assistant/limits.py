"""Usage limits for the Hannah demo, held in this API process's memory.

Two ceilings, both configurable: each account (HeroOS User) may send a few
messages per window, and the whole service a fixed number per minute and per
day, kept below the provider's shared free-tier quota. A request counts
against every ceiling only when all of them allow it.

These limits protect the shared quota from one runaway tab or a burst of
users. They are not durable or distributed: a restart or redeploy resets
them, and each API instance counts on its own (staging runs one). They are not
a security boundary (authentication, the administrator role and the demo
switch are). Keys are internal user ids, held in memory only and never logged.
"""

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

ACCOUNT_WINDOW_SECONDS = 300.0
MINUTE_SECONDS = 60.0
DAY_SECONDS = 86_400.0

LimitScope = Literal["account", "global"]


@dataclass(frozen=True, slots=True)
class LimitExceeded:
    scope: LimitScope
    # Seconds until a request would be allowed again.
    retry_after: int


class UsageLimits:
    def __init__(
        self,
        *,
        account_limit: int,
        global_per_minute: int,
        global_per_day: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._account_limit = account_limit
        self._global = ((global_per_minute, MINUTE_SECONDS), (global_per_day, DAY_SECONDS))
        self._clock = clock
        self._lock = threading.Lock()
        self._accounts: dict[str, deque[float]] = {}
        self._service: tuple[deque[float], deque[float]] = (deque(), deque())

    @staticmethod
    def _wait(hits: deque[float], limit: int, window: float, now: float) -> int | None:
        while hits and hits[0] <= now - window:
            hits.popleft()
        if len(hits) < limit:
            return None
        return max(1, int(hits[0] + window - now) + 1)

    def acquire(self, account: str) -> LimitExceeded | None:
        """Count one request for ``account``; None if allowed, else which ceiling was hit."""
        now = self._clock()
        with self._lock:
            mine = self._accounts.setdefault(account, deque())
            wait = self._wait(mine, self._account_limit, ACCOUNT_WINDOW_SECONDS, now)
            if wait is not None:
                return LimitExceeded("account", wait)
            for hits, (limit, window) in zip(self._service, self._global, strict=True):
                wait = self._wait(hits, limit, window, now)
                if wait is not None:
                    return LimitExceeded("global", wait)
            mine.append(now)
            for hits in self._service:
                hits.append(now)
            # Forget accounts with nothing left in their window.
            if len(self._accounts) > 1000:
                for key, hits in list(self._accounts.items()):
                    while hits and hits[0] <= now - ACCOUNT_WINDOW_SECONDS:
                        hits.popleft()
                    if not hits:
                        del self._accounts[key]
            return None
