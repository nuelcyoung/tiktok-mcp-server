"""Cache tests: repeats are free, simultaneous identical reads share one load."""

from __future__ import annotations

import asyncio

import pytest

from tiktokmcp.cache import TTLCache

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_repeat_reads_are_served_from_the_cache() -> None:
    cache = TTLCache(ttl_s=60)
    calls = 0

    async def loader() -> int:
        nonlocal calls
        calls += 1
        return calls

    assert await cache.get_or_load("k", loader) == (1, False)
    assert await cache.get_or_load("k", loader) == (1, True)
    assert calls == 1


async def test_simultaneous_identical_reads_share_one_load() -> None:
    cache = TTLCache(ttl_s=60)
    calls = 0

    async def loader() -> str:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        return "value"

    results = await asyncio.gather(*(cache.get_or_load("k", loader) for _ in range(5)))
    assert calls == 1
    assert {value for value, _ in results} == {"value"}


async def test_expired_entries_are_reloaded() -> None:
    cache = TTLCache(ttl_s=0.05)
    calls = 0

    async def loader() -> int:
        nonlocal calls
        calls += 1
        return calls

    await cache.get_or_load("k", loader)
    await asyncio.sleep(0.08)
    assert await cache.get_or_load("k", loader) == (2, False)


async def test_a_zero_ttl_disables_caching() -> None:
    cache = TTLCache(ttl_s=0)
    calls = 0

    async def loader() -> int:
        nonlocal calls
        calls += 1
        return calls

    await cache.get_or_load("k", loader)
    await cache.get_or_load("k", loader)
    assert calls == 2


async def test_the_cache_is_capped() -> None:
    cache = TTLCache(ttl_s=60, max_entries=2)

    async def loader(value: str) -> str:
        return value

    await cache.get_or_load("a", lambda: loader("a"))
    await cache.get_or_load("b", lambda: loader("b"))
    await cache.get_or_load("c", lambda: loader("c"))
    assert cache.peek("a") is None
    assert cache.peek("c") == "c"


async def test_invalidate_drops_matching_entries() -> None:
    cache = TTLCache(ttl_s=60)

    async def loader() -> str:
        return "value"

    await cache.get_or_load("search:cats", loader)
    await cache.get_or_load("profile:khaby", loader)
    cache.invalidate("search:")
    assert cache.peek("search:cats") is None
    assert cache.peek("profile:khaby") == "value"


async def test_cache_when_keeps_a_blocked_result_out_of_the_cache() -> None:
    cache = TTLCache(ttl_s=60)
    calls = 0

    async def loader() -> tuple[list[str], str | None]:
        nonlocal calls
        calls += 1
        return ([], "rate-limited") if calls == 1 else (["ok"], None)

    keep_real_reads = lambda result: bool(result[0])  # noqa: E731
    first, _ = await cache.get_or_load("k", loader, cache_when=keep_real_reads)
    second, _ = await cache.get_or_load("k", loader, cache_when=keep_real_reads)

    assert first == ([], "rate-limited")
    assert second == (["ok"], None)
    assert calls == 2


async def test_a_failed_load_is_not_cached() -> None:
    cache = TTLCache(ttl_s=60)
    attempts = 0

    async def loader() -> str:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("upstream said no")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await cache.get_or_load("k", loader)
    assert attempts == 2
