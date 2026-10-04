"""Block detection, caching, and browser-fingerprint helpers (no network, no browser)."""

from __future__ import annotations

from typing import Any, cast

import pytest

from tiktokmcp.browser import BrowserManager, _chrome_user_agent, _is_telemetry, default_profile_dir
from tiktokmcp.cache import TTLCache
from tiktokmcp.config import Settings
from tiktokmcp.scraper import TikTokScraper, _to_count, block_marker, blocked_note
from tiktokmcp.throttle import Throttle

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


BLOCKED_PAGES = [
    "Something went wrong. Please try again later.",
    "Too Many Requests",
    "Unusual traffic detected from your network",
    "Verify to continue",
    "Please Try Again Later",
    "Solve the puzzle to continue",
    "Access Denied",
]

# What a real page looks like: long enough that the ambiguous phrase in a
# caption cannot be mistaken for TikTok's blank error page.
REAL_PAGE_COPY = [
    "@khaby.lame | TikTok. 12.4M followers. 452 following. 4.1M likes. "
    "I make things move. Business: contact@khaby.com "
    "1.2M 2.3M 890K 4.1M 1.1M 745K 2.2M 980K "
    "That is the trick #home #diy #fyp #viral #lifehacks",
    "my page captions for the week: books, coffee, rain, and one very long recipe that "
    "went wrong in the middle but still turned out edible #baking #fail",
    "",
]


@pytest.mark.parametrize("text", BLOCKED_PAGES)
def test_blocked_pages_are_recognised(text: str) -> None:
    assert block_marker(text) is not None


@pytest.mark.parametrize("text", REAL_PAGE_COPY)
def test_normal_page_copy_is_not_a_block(text: str) -> None:
    assert block_marker(text) is None


def test_a_blank_error_page_is_a_block() -> None:
    assert block_marker("Something went wrong") == "went wrong"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (163000000, 163000000),
        ("452", 452),
        (0, 0),
        (None, None),
        ("not a number", None),
        # TikTok sends a negative sentinel instead of a count now and then.
        (-1610266554, None),
    ],
)
def test_counts_never_come_back_negative(raw: Any, expected: int | None) -> None:
    assert _to_count(raw) == expected


def test_block_note_tells_the_caller_how_long_to_wait() -> None:
    assert "Do not retry" in blocked_note(90)
    assert "2 minutes" in blocked_note(90.1)
    assert "1 minute" in blocked_note(30)


@pytest.mark.parametrize(
    ("url", "blocked"),
    [
        ("https://www.tiktok.com/@a", False),
        ("https://analytics.tiktok.com/api/log", True),
        ("https://ads.tiktokads.com/pixel", True),
        ("https://lf16-tiktokcdn.iesdouyin.com/obj/cover.jpg", False),
    ],
)
def test_only_telemetry_hosts_are_dropped(url: str, blocked: bool) -> None:
    assert _is_telemetry(url) is blocked


def test_the_user_agent_matches_the_running_browser() -> None:
    agent = _chrome_user_agent("131.0.6778.86")
    assert "Chrome/131.0.6778.86" in agent
    assert "Headless" not in agent
    assert "Safari/537.36" in agent


def test_the_profile_dir_is_a_cache_path() -> None:
    path = default_profile_dir()
    assert path.parts[-2:] == ("tiktok-mcp", "browser-profile")


def _scraper(ttl_s: float = 60) -> TikTokScraper:
    """A scraper with no browser: tests replace the one read it makes."""
    return TikTokScraper(
        cast(BrowserManager, None),
        Settings(),
        throttle=Throttle(),
        cache=TTLCache(ttl_s=ttl_s),
    )


def _grid_serving(scraper: TikTokScraper) -> dict[str, int]:
    """Stub the grid read, counting how many times it is actually called."""
    calls = {"n": 0}

    async def fake(url: str) -> tuple[list[dict[str, str]], str | None]:
        calls["n"] += 1
        return [{"username": "a", "id": "7300000000000000000", "views": "5", "title": "hi"}], None

    scraper._video_links = fake  # type: ignore[method-assign]
    return calls


@pytest.mark.anyio
async def test_a_repeated_grid_read_is_served_from_the_cache() -> None:
    scraper = _scraper()
    calls = _grid_serving(scraper)

    first = await scraper.get_videos("a", 5)
    second = await scraper.get_videos("a", 5)

    assert calls["n"] == 1
    assert (first.count, second.count) == (1, 1)
    assert second.videos[0].url == "https://www.tiktok.com/@a/video/7300000000000000000"


@pytest.mark.anyio
async def test_a_blocked_grid_is_never_cached() -> None:
    scraper = _scraper()
    calls = {"n": 0}

    async def blocked(url: str) -> tuple[list[dict[str, str]], str | None]:
        calls["n"] += 1
        return [], "TikTok is rate-limiting this client"

    scraper._video_links = blocked  # type: ignore[method-assign]

    first = await scraper.search_videos("cats", 5)
    second = await scraper.search_videos("cats", 5)

    assert calls["n"] == 2
    assert "rate-limiting" in cast(str, first.note)
    assert "rate-limiting" in cast(str, second.note)


@pytest.mark.anyio
async def test_a_zero_ttl_disables_the_cache_in_the_scraper() -> None:
    scraper = _scraper(ttl_s=0)
    calls = _grid_serving(scraper)

    await scraper.get_videos("a", 5)
    await scraper.get_videos("a", 5)
    assert calls["n"] == 2
