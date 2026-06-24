"""Order rate limiter (A-003): sliding-window counter per session.

Usage:
    limiter = OrderRateLimiter(max_rate=10, window_seconds=1)
    if limiter.allow():
        # submit order
    else:
        # skip (rate limited)
"""
from __future__ import annotations

import time
from collections import deque


class OrderRateLimiter:
    """Sliding-window rate limiter.

    Tracks call timestamps in a deque. When the window is full (max_rate
    reached within window_seconds), allow() returns False.
    """

    def __init__(self, max_rate: int = 10, window_seconds: int = 1) -> None:
        self.max_rate = max_rate
        self.window = window_seconds
        self.timestamps: deque[float] = deque(maxlen=max_rate)

    def allow(self) -> bool:
        now = time.time()
        cutoff = now - self.window
        while self.timestamps and self.timestamps[0] < cutoff:
            self.timestamps.popleft()
        if len(self.timestamps) >= self.max_rate:
            return False
        self.timestamps.append(now)
        return True
