"""Short-lived result cache with single-flight de-duplication.

Re-reading the same profile or running the same search twice is normal when a
model retries or re-plans, and every repeat would otherwise be another page
load. Caching makes repeats free; the per-key lock makes two simultaneous
identical requests share one load instead of racing to the same URL.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class TTLCache:
    def __init__(self, ttl_s: float = 300.0, max_entries: int = 128) -> None:
        self.ttl_s = ttl_s
        self.max_entries = max(1, max_entries)
        self._entries: OrderedDict[str, tuple[float, object]] = OrderedDict()
        self._locks: dict[str, asyncio.Lock] = {}

    def peek(self, key: str) -> object | None:
        """The cached value for ``key``, or None when absent or expired."""
        return self._fresh(key)

    async def get_or_load(
        self,
        key: str,
        loader: Callable[[], Awaitable[T]],
        *,
        cache_when: Callable[[T], bool] | None = None,
    ) -> tuple[T, bool]:
        """Return ``(value, was_cached)``, loading it at most once per TTL window.

        ``cache_when`` decides what is worth keeping: callers use it to store a
        real read but not an empty or rate-limited one.
        """
        if self.ttl_s <= 0:
            return await loader(), False

        hit = self._fresh(key)
        if hit is not None:
            logger.debug("Cache hit for %s", key)
            return hit, True  # type: ignore[return-value]

        async with self._lock_for(key):
            # Another caller may have loaded this key while we waited for the lock.
            hit = self._fresh(key)
            if hit is not None:
                return hit, True  # type: ignore[return-value]
            value = await loader()
            if cache_when is None or cache_when(value):
                self._store(key, value)
            return value, False

    def invalidate(self, prefix: str = "") -> None:
        """Drop entries whose key starts with ``prefix`` (all entries when empty)."""
        for key in [k for k in self._entries if k.startswith(prefix)]:
            self._entries.pop(key, None)

    def _lock_for(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = self._locks[key] = asyncio.Lock()
            if len(self._locks) > 2 * self.max_entries:
                for stale in [k for k, held in self._locks.items() if not held.locked()]:
                    self._locks.pop(stale, None)
        return lock

    def _fresh(self, key: str) -> object | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= time.monotonic():
            self._entries.pop(key, None)
            return None
        self._entries.move_to_end(key)
        return value

    def _store(self, key: str, value: object) -> None:
        self._entries[key] = (time.monotonic() + self.ttl_s, value)
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
