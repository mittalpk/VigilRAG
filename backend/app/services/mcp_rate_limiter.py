"""
MCP gateway rate limiter — separate pool from human UI users (US-037 / NFR-002).

In-process sliding-window limiter keyed by API key id. Sufficient for single-
instance MVP; multi-instance deployments should back this with Redis.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
import os
import time
from typing import Deque, Dict


@dataclass
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: float = 0.0


class SlidingWindowRateLimiter:
    """Thread-safe per-key sliding window rate limiter."""

    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max(1, int(max_requests))
        self.window_seconds = max(1.0, float(window_seconds))
        self._events: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str) -> RateLimitResult:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            q = self._events[key]
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= self.max_requests:
                retry = self.window_seconds - (now - q[0]) if q else self.window_seconds
                return RateLimitResult(
                    allowed=False,
                    limit=self.max_requests,
                    remaining=0,
                    retry_after_seconds=max(0.0, retry),
                )
            q.append(now)
            remaining = self.max_requests - len(q)
            return RateLimitResult(
                allowed=True,
                limit=self.max_requests,
                remaining=max(0, remaining),
            )

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._events.clear()
            elif key in self._events:
                del self._events[key]


def _default_limiter() -> SlidingWindowRateLimiter:
    limit = int(os.getenv("MCP_RATE_LIMIT_PER_MINUTE", "60"))
    window = float(os.getenv("MCP_RATE_LIMIT_WINDOW_SECONDS", "60"))
    return SlidingWindowRateLimiter(max_requests=limit, window_seconds=window)


# Process-wide MCP pool (separate from any future human-user limiter)
mcp_rate_limiter = _default_limiter()
