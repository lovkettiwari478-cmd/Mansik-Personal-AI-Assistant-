"""In-process sliding-window rate limiter.

For single-process deployments this is exact. For multi-worker production
deployments, swap ``RateLimiter`` for a Redis-backed implementation (the
interface is intentionally tiny) — see docs/DEPLOYMENT.md.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field


@dataclass
class _Window:
    hits: deque = field(default_factory=deque)


class RateLimiter:
    def __init__(self) -> None:
        self._windows: dict[str, _Window] = defaultdict(_Window)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_seconds: int = 60) -> tuple[bool, float]:
        """Record a hit. Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        with self._lock:
            win = self._windows[key]
            # prune entries outside the window
            while win.hits and now - win.hits[0] > window_seconds:
                win.hits.popleft()
            if len(win.hits) >= limit:
                retry_after = window_seconds - (now - win.hits[0])
                return False, max(retry_after, 0.1)
            win.hits.append(now)
            # opportunistic cleanup of stale keys (bounded memory)
            if len(self._windows) > 50_000:
                stale = [k for k, w in self._windows.items()
                         if not w.hits or now - w.hits[-1] > window_seconds * 10]
                for k in stale[:10_000]:
                    del self._windows[k]
            return True, 0.0

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._windows.clear()
            else:
                self._windows.pop(key, None)


limiter = RateLimiter()
