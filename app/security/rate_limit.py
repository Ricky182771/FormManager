from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from starlette.requests import Request

from app.config import RateLimit

SWEEP_INTERVAL_SECONDS = 60
STALE_AFTER_SECONDS = 2 * 3600


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    retry_after: int


class SlidingWindowRateLimiter:
    """In-memory limiter for abuse control only, never for identity or integrity.

    Correct with a single worker process. Keys (client IPs) live only in memory and are
    dropped as their windows expire; they are never written to disk or logs.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()
        self._last_sweep = clock()

    def hit(self, bucket: str, key: str, rule: RateLimit) -> RateDecision:
        now = self._clock()
        with self._lock:
            self._maybe_sweep(now)
            window = self._hits.setdefault((bucket, key), deque())
            cutoff = now - rule.window_seconds
            while window and window[0] <= cutoff:
                window.popleft()
            if len(window) >= rule.limit:
                retry = math.ceil(window[0] + rule.window_seconds - now)
                return RateDecision(False, max(retry, 1))
            window.append(now)
            return RateDecision(True, 0)

    def tracked_keys(self) -> int:
        with self._lock:
            return len(self._hits)

    def _maybe_sweep(self, now: float) -> None:
        if now - self._last_sweep < SWEEP_INTERVAL_SECONDS:
            return
        self._last_sweep = now
        horizon = now - STALE_AFTER_SECONDS
        stale = [k for k, w in self._hits.items() if not w or w[-1] < horizon]
        for key in stale:
            del self._hits[key]


def client_ip(request: Request) -> str:
    # Uvicorn runs with --proxy-headers behind Caddy, which overwrites X-Forwarded-For.
    return request.client.host if request.client else "unknown"
