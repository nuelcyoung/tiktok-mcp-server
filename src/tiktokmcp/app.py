"""Server-wide state created by the lifespan and handed to every tool call."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mcp.server.mcpserver import Context

from tiktokmcp.browser import BrowserManager
from tiktokmcp.config import Settings
from tiktokmcp.scraper import TikTokScraper
from tiktokmcp.transcribe import Transcriber

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer


@dataclass(frozen=True, slots=True)
class AppContext:
    settings: Settings
    browser: BrowserManager
    scraper: TikTokScraper
    transcriber: Transcriber


def build_app_context(settings: Settings) -> AppContext:
    browser = BrowserManager(headless=settings.headless)
    return AppContext(
        settings=settings,
        browser=browser,
        scraper=TikTokScraper(browser, settings),
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
