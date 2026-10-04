"""Server-wide state created by the lifespan and handed to every tool call."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mcp.server.mcpserver import Context

from tiktokmcp.browser import BrowserManager
from tiktokmcp.cache import TTLCache
from tiktokmcp.config import Settings
from tiktokmcp.scraper import TikTokScraper
from tiktokmcp.throttle import Throttle
from tiktokmcp.transcribe import Transcriber

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer


@dataclass(frozen=True, slots=True)
class AppContext:
    settings: Settings
    throttle: Throttle
    cache: TTLCache
    browser: BrowserManager
    scraper: TikTokScraper
    transcriber: Transcriber


def build_app_context(settings: Settings) -> AppContext:
    # One throttle for the whole server: the browser's warm-up visit, every
    # scrape, and every media download all take a slot from the same window.
    throttle = Throttle(
        min_interval_s=settings.min_interval_s,
        max_requests_per_window=settings.max_requests_per_window,
        window_s=settings.request_window_s,
        cooldown_base_s=settings.cooldown_base_s,
        cooldown_max_s=settings.cooldown_max_s,
    )
    cache = TTLCache(ttl_s=settings.cache_ttl_s)
    browser = BrowserManager(settings, throttle)
    return AppContext(
        settings=settings,
        throttle=throttle,
        cache=cache,
        browser=browser,
        scraper=TikTokScraper(browser, settings, throttle=throttle, cache=cache),
        transcriber=Transcriber(settings),
    )


def make_lifespan(settings: Settings):
    @asynccontextmanager
    async def lifespan(_: MCPServer[Any]) -> AsyncIterator[AppContext]:
        app = build_app_context(settings)
        try:
            yield app
        finally:
            await app.browser.close()

    return lifespan


def get_app(ctx: Context) -> AppContext:
    return ctx.request_context.lifespan_context
