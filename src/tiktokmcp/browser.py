"""Playwright Chromium lifecycle, owned by the server lifespan.

The browser launches lazily on the first tool call (so ``initialize`` and
``tools/list`` stay fast) and is shared by every call until shutdown.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from playwright.async_api import Browser, Page, Playwright, async_playwright
from playwright.async_api import Error as PlaywrightError

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
HOME_URL = "https://www.tiktok.com/"


def install_chromium() -> None:
    """Download Playwright's Chromium (first run under uvx/pipx, where no install script ran).

    Output is captured: on the stdio transport, stdout carries the JSON-RPC stream.
    """
    logger.info("Chromium not found; downloading it once (about 150 MB)...")
    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(f"playwright install chromium failed: {result.stderr[-500:]}")
    logger.info("Chromium installed")


class BrowserManager:
    def __init__(self, *, headless: bool = True) -> None:
        self._headless = headless
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()

    async def _get_browser(self) -> Browser:
        if self._browser is not None and self._browser.is_connected():
            return self._browser
        async with self._lock:
            # Re-check inside the lock: a concurrent caller may have launched it.
            if self._browser is not None and self._browser.is_connected():
                return self._browser
            if self._playwright is not None:
                await self._playwright.stop()
            self._playwright = await async_playwright().start()
            try:
                self._browser = await self._playwright.chromium.launch(headless=self._headless)
            except PlaywrightError as exc:
                if "Executable doesn't exist" not in str(exc):
                    raise
                await asyncio.to_thread(install_chromium)
                self._browser = await self._playwright.chromium.launch(headless=self._headless)
            logger.info("Playwright Chromium launched")
        return self._browser

    @asynccontextmanager
    async def page(self) -> AsyncIterator[Page]:
        """Yield a cookie-warmed page in a fresh context; closes the context on exit.

        Visiting the TikTok homepage first (networkidle + 2s) sets the cookies
        that TikTok's anti-bot checks look for before the target page loads.
        """
        browser = await self._get_browser()
        context = await browser.new_context(user_agent=USER_AGENT)
        try:
            page = await context.new_page()
            await page.goto(HOME_URL, wait_until="networkidle", timeout=45_000)
            await page.wait_for_timeout(2_000)
            yield page
        finally:
            await context.close()

    async def close(self) -> None:
        async with self._lock:
            if self._browser is not None:
                await self._browser.close()
                self._browser = None
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None
