"""Pacing and backoff tests. These use sub-second intervals and never sleep long."""

from __future__ import annotations

import time

import pytest

from tiktokmcp.throttle import Throttle

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def quiet(**overrides) -> Throttle:
    """A throttle with jitter off, so every assertion is exact."""
    options = {
        "min_interval_s": 0.0,
        "max_requests_per_window": 1000,
        "window_s": 0.1,
        "cooldown_base_s": 0.0,
        "cooldown_max_s": 0.0,
        "jitter_ratio": 0.0,
    }
    return Throttle(**{**options, **overrides})


async def test_requests_are_spaced_by_the_minimum_interval() -> None:
    throttle = quiet(min_interval_s=0.05)
    start = time.monotonic()
    for _ in range(3):
        await throttle.slot()
    assert time.monotonic() - start >= 0.09


async def test_concurrent_callers_queue_instead_of_bursting() -> None:
    throttle = quiet(min_interval_s=0.05)
    start = time.monotonic()
    await_three = [throttle.slot() for _ in range(3)]
    for pending in await_three:
        await pending
    assert time.monotonic() - start >= 0.09


async def test_sliding_window_holds_the_budget() -> None:
    throttle = quiet(max_requests_per_window=2, window_s=0.2)
    await throttle.slot()
    await throttle.slot()
    start = time.monotonic()
    await throttle.slot()
    assert time.monotonic() - start >= 0.15


async def test_a_block_makes_the_next_call_wait() -> None:
    throttle = quiet(cooldown_base_s=0.2, cooldown_max_s=0.2)
    throttle.report_block("HTTP 429")
    assert throttle.cooldown_remaining_s() > 0
    start = time.monotonic()
    await throttle.slot()
    assert time.monotonic() - start >= 0.15


def test_cooldown_doubles_on_repeated_blocks() -> None:
    throttle = quiet(cooldown_base_s=10, cooldown_max_s=1000)
    assert throttle.report_block("one") == 10
    assert throttle.report_block("two") == 20
    assert throttle.report_block("three") == 40


def test_cooldown_is_capped() -> None:
    throttle = quiet(cooldown_base_s=10, cooldown_max_s=25)
    for _ in range(6):
        throttle.report_block("HTTP 429")
    assert throttle.cooldown_remaining_s() <= 25


def test_a_served_page_resets_the_streak() -> None:
    throttle = quiet(cooldown_base_s=10, cooldown_max_s=1000)
    throttle.report_block("one")
    throttle.report_block("two")
    throttle.report_success()
    assert throttle.report_block("three") == 10


def test_jitter_never_shortens_a_wait() -> None:
    throttle = Throttle(cooldown_base_s=60, cooldown_max_s=60, jitter_ratio=0.3)
    assert all(throttle.report_block("HTTP 429") >= 60 * 0.85 for _ in range(25))
