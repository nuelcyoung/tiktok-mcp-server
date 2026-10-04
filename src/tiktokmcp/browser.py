"""Playwright Chromium lifecycle, owned by the server lifespan.

TikTok's bot check looks at three things this module takes care of:

* **Identity continuity** - one persistent browser profile holds the cookies
  (``ttwid``, ``msToken``) across calls and restarts, so repeat reads come from
  the same "device" instead of a throwaway incognito context each time.
* **Fingerprint** - the ``HeadlessChrome`` token and ``navigator.webdriver``
  are replaced, and the version in the user agent is read from the browser
  that actually runs so the headers stay self-consistent.
* **Request volume** - the homepage is warmed up once per session instead of
  before every page, and TikTok's ad and telemetry calls are dropped, since
  nothing we read comes from them.

The browser launches lazily on the first tool call (so ``initialize`` and
``tools/list`` stay fast) and is shared by every call until shutdown.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright
from playwright.async_api import Error as PlaywrightError

from tiktokmcp.config import Settings
from tiktokmcp.throttle import Throttle

logger = logging.getLogger(__name__)

HOME_URL = "https://www.tiktok.com/"
ACCEPT_LANGUAGE = "en-US,en;q=0.9"
WARMUP_MS = 2_500
VIEWPORT = {"width": 1440, "height": 900}

# Installed browsers are less closely fingerprinted than bundled Chromium, so
# prefer a real Chrome or Edge when one is present. None = bundled Chromium.
AUTO_CHANNELS = ("chrome", "msedge", "chromium")

# Prefixes of TikTok's own ad and telemetry endpoints: pure overhead for us.
TELEMETRY_HOSTS = (
    ".tiktokads.com",
    ".byteoversea.com",
    ".bytedance.com",
    ".ibytedtos.com",
    ".tiktokv.com",
    "analytics.tiktok.com",
    "log.tiktok.com",
)

LAUNCH_ARGS = (
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--no-first-run",
    "--no-default-browser-check",
)

# Removes the handful of properties that give a scripted browser away.
STEALTH_SCRIPT = """
Object.defineProperty(Navigator.prototype, 'webdriver', { get: () => undefined });
if (!window.chrome) window.chrome = { runtime: {} };
Object.defineProperty(Navigator.prototype, 'languages', { get: () => ['en-US', 'en'] });
const query = navigator.permissions.query.bind(navigator.permissions);
navigator.permissions.query = (params) =>
  params.name === 'notifications'
    ? Promise.resolve({ state: Notification.permission, onchange: null })
    : query(params);
"""

_VERSION_RE = re.compile(r"\d+\.\d+\.\d+\.\d+")


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


def default_profile_dir() -> Path:
    base = (
        Path(os.environ["LOCALAPPDATA"])
        if sys.platform == "win32" and os.environ.get("LOCALAPPDATA")
        else Path.home() / "Library" / "Caches"
        if sys.platform == "darwin"
        else Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    )
    return base / "tiktok-mcp" / "browser-profile"


def _chrome_user_agent(version: str) -> str:
    """A stock Chrome user agent whose version matches the running browser."""
    os_part = (
        "Windows NT 10.0; Win64; x64"
        if sys.platform == "win32"
        else "Macintosh; Intel Mac OS X 10_15_7"
        if sys.platform == "darwin"
        else "X11; Linux x86_64"
    )
    return (
        f"Mozilla/5.0 ({os_part}) AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{version or '131.0.0.0'} Safari/537.36"
    )


def _is_telemetry(url: str) -> bool:
    lowered = url.lower()
    return any(host in lowered for host in TELEMETRY_HOSTS)


async def _route_request(route) -> None:
    """Drop TikTok's ad and telemetry calls, which serve nothing we read.

    Media and fonts are deliberately *not* blocked: aborting them changes
    TikTok's lazy-loading behaviour and makes the page fetch more, not fewer.
    """
    if _is_telemetry(route.request.url):
        await route.abort()
        return
    await route.continue_()


class BrowserManager:
    def __init__(self, settings: Settings, throttle: Throttle) -> None:
        self._settings = settings
        self._throttle = throttle
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._browser: Browser | None = None  # only for the temporary-profile fallback
        self._lock = asyncio.Lock()
        self._chrome_version = ""

    async def _get_browser(self) -> BrowserContext:
        if self._context is not None:
            return self._context
        async with self._lock:
            # Re-check inside the lock: a concurrent caller may have launched it.
            if self._context is not None:
                return self._context
            self._playwright = await async_playwright().start()
            try:
                self._context = await self._launch_context(self._playwright)
            except BaseException:
                await self._dispose()
                raise
            self._context.set_default_timeout(self._settings.navigation_timeout_ms)
            await self._warm_up(self._context)
            logger.info("Playwright Chromium ready")
        return self._context

    async def _launch_context(self, playwright: Playwright) -> BrowserContext:
        """Open the first browser build that works, then harden it."""
        wanted = self._settings.browser_channel
        channels = [wanted] if wanted else [*AUTO_CHANNELS, None]
        for channel in channels:
            context = await self._try_launch(playwright, channel)
            if context is None:
                continue
            logger.info("Browsing TikTok with %s", channel or "bundled Chromium")
            await context.add_init_script(STEALTH_SCRIPT)
            if self._settings.block_telemetry:
                await context.route("**/*", _route_request)
            return context
        raise PlaywrightError("could not launch any Chromium build")

    async def _try_launch(self, playwright: Playwright, channel: str | None) -> BrowserContext | None:
        """Launch one browser build, preferring a persistent profile."""
        if self._settings.persist_profile:
            context = await self._persistent_context(playwright, channel)
            if context is not None:
                return context
        browser = await playwright.chromium.launch(channel=channel, **self._launch_options())
        self._browser = browser
        return await browser.new_context(**self._context_options())

    async def _persistent_context(self, playwright: Playwright, channel: str | None) -> BrowserContext | None:
        """A profile directory keeps TikTok's cookies across calls and restarts."""
        profile_dir = Path(self._settings.profile_dir or default_profile_dir())
        await asyncio.to_thread(profile_dir.mkdir, parents=True, exist_ok=True)
        try:
            return await self._open_profile(playwright, channel, profile_dir)
        except PlaywrightError as exc:
            if "Executable doesn't exist" in str(exc) and channel is None:
                await asyncio.to_thread(install_chromium)
                return await self._open_profile(playwright, None, profile_dir)
            # A profile locked by another server process is normal on a shared
            # machine: fall back to a throwaway one rather than fail the call.
            logger.warning("Persistent browser profile unavailable (%s); using a temporary one", exc)
            return None

    async def _open_profile(
        self, playwright: Playwright, channel: str | None, profile_dir: Path
    ) -> BrowserContext:
        return await playwright.chromium.launch_persistent_context(
            str(profile_dir), channel=channel, **self._launch_options(), **self._context_options()
        )

    def _launch_options(self) -> dict[str, Any]:
        return {"headless": self._settings.headless, "args": list(LAUNCH_ARGS)}

    def _context_options(self) -> dict[str, Any]:
        """A plain desktop Chrome identity: locale, size, and language agree."""
        return {
            "locale": "en-US",
            "timezone_id": "America/New_York",
            "viewport": dict(VIEWPORT),
            "screen": dict(VIEWPORT),
            "device_scale_factor": 1,
            "has_touch": False,
            "is_mobile": False,
            "extra_http_headers": {"Accept-Language": ACCEPT_LANGUAGE},
        }

    async def _warm_up(self, context: BrowserContext) -> None:
        """One homepage visit per session sets the cookies TikTok checks before content."""
        page = await context.new_page()
        try:
            await self._throttle.slot()
            await page.goto(
                HOME_URL,
                wait_until="domcontentloaded",
                timeout=self._settings.navigation_timeout_ms,
            )
            await page.wait_for_timeout(WARMUP_MS)
        except PlaywrightError:
            logger.warning("TikTok warm-up visit failed; continuing without it", exc_info=True)
        finally:
            await self._close(page)

    async def _mask_automation(self, context: BrowserContext, page: Page) -> Any:
        """Replace the headless user agent, keeping its version honest.

        ``navigator.webdriver`` is handled by the init script; the user agent is
        set over CDP because Playwright only accepts it at context creation and
        we need the real browser version first.

        The session is returned instead of detached: the override lives and dies
        with it, so detaching here would silently put ``HeadlessChrome`` back.
        """
        try:
            cdp = await context.new_cdp_session(page)
        except PlaywrightError:
            logger.debug("No CDP session; leaving the user agent as-is")
            return None
        try:
            self._chrome_version = self._chrome_version or await self._read_version(cdp)
            await cdp.send(
                "Network.setUserAgentOverride",
                {
                    "userAgent": _chrome_user_agent(self._chrome_version),
                    "acceptLanguage": ACCEPT_LANGUAGE,
                    "platform": "Win32" if sys.platform == "win32" else "MacIntel",
                },
            )
        except PlaywrightError:
            logger.debug("Could not override the headless user agent", exc_info=True)
            with contextlib.suppress(PlaywrightError):
                await cdp.detach()
            return None
        return cdp

    async def _read_version(self, cdp) -> str:
        """The Chrome version string of the browser that actually runs."""
        info = await cdp.send("Browser.getVersion")
        found = _VERSION_RE.search(str(info.get("product", "")))
        return found.group(0) if found else ""

    @asynccontextmanager
    async def page(self) -> AsyncIterator[Page]:
        """Yield a page in the shared profile. Cookies and fingerprint persist."""
        context = await self._get_browser()
        page = await context.new_page()
        cdp = await self._mask_automation(context, page)
        try:
            yield page
        finally:
            await self._close(page, cdp)

    async def _close(self, page: Page, cdp: Any = None) -> None:
        if cdp is not None:
            with contextlib.suppress(PlaywrightError):
                await cdp.detach()
        with contextlib.suppress(PlaywrightError):
            await page.close()

    async def _dispose(self) -> None:
        for resource in (self._context, self._browser):
            if resource is not None:
                with contextlib.suppress(PlaywrightError):
                    await resource.close()
        self._context = None
        self._browser = None
        if self._playwright is not None:
            with contextlib.suppress(Exception):
                await self._playwright.stop()
            self._playwright = None

    async def close(self) -> None:
        async with self._lock:
            await self._dispose()
