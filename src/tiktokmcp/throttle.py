"""Pacing and backoff for TikTok traffic."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import deque

logger = logging.getLogger(__name__)


class Throttle:
    """A single server-wide gate in front of every TikTok request."""

    def __init__(
        self,
        *,
        min_interval_s: float = 4.0,
        max_requests_per_window: int = 24,
        window_s: float = 300.0,
        cooldown_base_s: float = 90.0,
        cooldown_max_s: float = 900.0,
        jitter_ratio: float = 0.3,
    ) -> None:
        self.min_interval_s = max(0.0, min_interval_s)
        self.max_requests_per_window = max(1, max_requests_per_window)
        self.window_s = max(0.1, window_s)
        self.cooldown_base_s = max(0.0, cooldown_base_s)
        self.cooldown_max_s = max(self.cooldown_base_s, cooldown_max_s)
        self.jitter_ratio = max(0.0, jitter_ratio)
        self._lock = asyncio.Lock()
        self._history: deque[float] = deque()
        self._next_free = 0.0
        self._cooldown_until = 0.0
        self._strikes = 0

    async def slot(self) -> float:
        """Wait for this request's turn and record it. Returns the seconds waited."""
        async with self._lock:
            waited = self._delay()
            if waited > 0:
                logger.info("Pacing TikTok traffic: waiting %.1fs before the next request", waited)
                await asyncio.sleep(waited)
            now = time.monotonic()
            self._history.append(now)
            while len(self._history) > self.max_requests_per_window:
                self._history.popleft()
            self._next_free = now + self.min_interval_s
            return waited

    def report_success(self) -> None:
        """A page rendered: the session is healthy, so the next block starts over."""
        if self._strikes:
            logger.info("TikTok is serving pages again; resetting the backoff streak")
            self._strikes = 0

    def report_block(self, reason: str) -> float:
        """Start or extend a cooldown after a block. Returns the cooldown in seconds."""
        self._strikes += 1
        cooldown = min(self.cooldown_base_s * 2 ** (self._strikes - 1), self.cooldown_max_s)
        cooldown = self._jitter(cooldown)
        self._cooldown_until = max(self._cooldown_until, time.monotonic() + cooldown)
        logger.warning(
            "TikTok looks like it is rate-limiting this client (%s). Cooling down for %.0fs (strike %d).",
            reason,
            cooldown,
            self._strikes,
        )
        return cooldown

    def cooldown_remaining_s(self) -> float:
        """Seconds left on an active cooldown."""
        return max(0.0, self._cooldown_until - time.monotonic())

    def _delay(self) -> float:
        now = time.monotonic()
        delay = max(self._next_free, self._cooldown_until) - now
        if len(self._history) >= self.max_requests_per_window:
            # The window is full: wait for the oldest request to age out of it.
            delay = max(delay, self._history[0] + self.window_s - now)
        return self._jitter(delay) if delay > 0 else 0.0

    def _jitter(self, seconds: float) -> float:
        """Spread waits out so the pattern is not machine-regular."""
        if not self.jitter_ratio or seconds <= 0:
            return max(0.0, seconds)
        return seconds * (1 - self.jitter_ratio / 2 + random.random() * self.jitter_ratio)
