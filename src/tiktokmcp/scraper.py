"""TikTok page scraping: profile JSON, video grids, search results, comments.

Every navigation goes through the shared throttle and every successful read is
cached for a few minutes.
"""

from __future__ import annotations

import logging
import math
import urllib.parse
from typing import Any

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from tiktokmcp.browser import BrowserManager
from tiktokmcp.cache import TTLCache
from tiktokmcp.config import Settings
from tiktokmcp.errors import NotFoundError
from tiktokmcp.models import (
    Comment,
    CommentList,
    Creator,
    CreatorList,
    Profile,
    SearchResults,
    VideoList,
    VideoSummary,
)
from tiktokmcp.throttle import Throttle

logger = logging.getLogger(__name__)

BASE_URL = "https://www.tiktok.com"

# HTTP statuses TikTok returns instead of content when it is pushing back.
BLOCK_STATUSES = frozenset({403, 405, 429, 503})

# Page copy that means TikTok pushed back. Unambiguous phrases, safe to match
# anywhere in the page.
BLOCK_MARKERS = (
    "too many requests",
    "unusual traffic",
    "access denied",
    "verify to continue",
    "solve the puzzle",
    "please try again later",
)

# TikTok's blank error page says "went wrong" and little else. A caption that
# merely contains those words sits inside a full page, so this phrase only
# counts as a block when the page is essentially empty.
AMBIGUOUS_MARKER = "went wrong"
EMPTY_PAGE_CHARS = 120

# Reads a key path out of the server-rendered rehydration JSON.
_JS_UNIVERSAL_DATA = """({ scope, path }) => {
    const el = document.getElementById("__UNIVERSAL_DATA_FOR_REHYDRATION__");
    if (!el) return null;
    try {
        let result = JSON.parse(el.textContent || "").__DEFAULT_SCOPE__?.[scope];
        for (const part of path.split(".")) {
            if (result == null) return null;
            result = result[part];
        }
        return result ?? null;
    } catch {
        return null;
    }
}"""

# True once a video grid has rendered or TikTok shows an error/empty state.
_JS_GRID_READY = """() => document.querySelectorAll('a[href*="/video/"]').length > 0
    || document.body.innerText.includes("went wrong")"""

# Every unique video link on the page, with the first two text lines of its
# card (TikTok renders views on line 0 and the caption on line 1).
_JS_VIDEO_LINKS = """() => {
    const out = [];
    const seen = new Set();
    for (const link of document.querySelectorAll('a[href*="/video/"]')) {
        const href = link.getAttribute("href") || "";
        if (seen.has(href)) continue;
        seen.add(href);
        const match = href.match(/\\/@([^/]+)\\/video\\/(\\d+)/);
        if (!match) continue;
        let card = link;
        for (let i = 0; i < 4 && card.parentElement; i++) card = card.parentElement;
        const lines = (card.innerText || "").split("\\n").map(l => l.trim()).filter(Boolean);
        out.push({ username: match[1], id: match[2], views: lines[0] || "0", title: lines[1] || "" });
    }
    return out;
}"""

_JS_COMMENTS_READY = """() => {
    const wrapper = document.querySelector('[class*="DivCommentItemWrappe"]');
    if (!wrapper) return false;
    return !wrapper.querySelector(".TUXSkeletonRectangle")
        && wrapper.textContent?.trim().length > 0;
}"""

_JS_COMMENTS = """(limit) => {
    const wrappers = document.querySelectorAll('[class*="DivCommentItemWrappe"]');
    return Array.from(wrappers).slice(0, limit).map(wrapper => {
        const allText = wrapper.textContent?.trim() || "";
        const lines = allText.split("\\n").map(l => l.trim()).filter(Boolean);
        const author = wrapper.querySelector('a[href*="/@"]')?.textContent?.trim() || "";
        const text = lines
            .filter(l => l !== author && !/^\\d/.test(l) && !/^(reply|replies|·)/i.test(l))
            .join(" ");
        const likesMatch = allText.match(/(\\d[\\d.]*[KMB]?)\\s*(?:likes?|like)/i)
            || allText.match(/(\\d[\\d.]*[KMB]?)$/);
        return { author, text: text.slice(0, 200), likes: likesMatch?.[1] || "0" };
    }).filter(c => c.text.length > 0);
}"""


def _search_url(query: str) -> str:
    return f"{BASE_URL}/search?q={urllib.parse.quote(query, safe='')}"


EMPTY_NOTE = "No results found."


def block_marker(text: str) -> str | None:
    """The reason phrase in ``text`` that shows TikTok refused the request."""
    body = text or ""
    lowered = body.lower()
    marker = next((phrase for phrase in BLOCK_MARKERS if phrase in lowered), None)
    if marker:
        return marker
    if AMBIGUOUS_MARKER in lowered and len(body.strip()) <= EMPTY_PAGE_CHARS:
        return AMBIGUOUS_MARKER
    return None


def blocked_note(cooldown_s: float) -> str:
    minutes = max(1, math.ceil(cooldown_s / 60))
    return (
        f"TikTok is rate-limiting this client, so nothing was returned. Do not retry for about "
        f"{minutes} minute{'s' if minutes > 1 else ''}; gather other data meanwhile."
    )


def _note(note: str | None, items: list[Any]) -> str | None:
    """The block note if there is one, otherwise explain an empty result."""
    return note or (None if items else EMPTY_NOTE)


def _to_count(value: Any) -> int | None:
    """A count, or None when TikTok sends something unusable.

    The stats block sometimes carries a negative sentinel instead of a number
    (``likeCount: -1610266554``), which is worse than no value at all.
    """
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _to_summary(raw: dict[str, str]) -> VideoSummary:
    return VideoSummary(
        id=raw["id"],
        title=raw["title"][:150],
        url=f"{BASE_URL}/@{raw['username']}/video/{raw['id']}",
        creator=raw["username"],
        views=raw["views"],
    )


class TikTokScraper:
    def __init__(
        self,
        browser: BrowserManager,
        settings: Settings,
        *,
        throttle: Throttle,
        cache: TTLCache,
    ) -> None:
        self._browser = browser
        self._settings = settings
        self._throttle = throttle
        self._cache = cache

    async def _visit(self, page: Page, url: str, ready: str | None = None) -> str | None:
        """Navigate under the throttle and wait for the page to render.

        Returns a note only for a hard block (an HTTP status that means TikTok
        refused the request outright). TikTok also fails *parts* of a page with
        an inline error panel while serving the rest, so page copy is judged
        later by :meth:`_block_note`, once we know what actually came back.
        """
        await self._throttle.slot()
        response = await page.goto(
            url, wait_until="domcontentloaded", timeout=self._settings.navigation_timeout_ms
        )
        status = response.status if response is not None else None
        if status in BLOCK_STATUSES:
            return self._block(f"HTTP {status}")

        if ready:
            await self._wait_for(page, ready)
        await page.wait_for_timeout(self._settings.settle_ms)
        self._throttle.report_success()
        return None

    async def _block_note(self, page: Page) -> str | None:
        """Start a cooldown if this page shows TikTok refused us, else nothing."""
        marker = block_marker(await page.evaluate("document.body.innerText"))
        return self._block(marker) if marker else None

    def _block(self, reason: str) -> str:
        """Start a cooldown and return the note explaining it to the caller."""
        return blocked_note(self._throttle.report_block(reason))

    async def _wait_for(self, page: Page, predicate: str) -> None:
        """Best-effort wait: an empty page is a valid (empty) result, not an error."""
        try:
            await page.wait_for_function(predicate, timeout=self._settings.render_timeout_ms)
        except PlaywrightTimeoutError:
            logger.debug("Render wait timed out on %s", page.url)

    async def _video_links(self, url: str) -> tuple[list[dict[str, str]], str | None]:
        """Return the page's video links and, when there are none, a note saying why."""
        async with self._browser.page() as page:
            note = await self._visit(page, url, _JS_GRID_READY)
            links = [] if note else await page.evaluate(_JS_VIDEO_LINKS)
            if not links and not note:
                note = await self._block_note(page)
        return links, note

    async def get_profile(self, username: str) -> Profile:
        async def load() -> Profile:
            async with self._browser.page() as page:
                note = await self._visit(page, f"{BASE_URL}/@{username}")
                args = {"scope": "webapp.user-detail"}
                user = (
                    {} if note else await page.evaluate(_JS_UNIVERSAL_DATA, {**args, "path": "userInfo.user"})
                )
                stats = await page.evaluate(_JS_UNIVERSAL_DATA, {**args, "path": "userInfo.stats"}) or {}
                if not user:
                    blocked = note or await self._block_note(page)
                    raise NotFoundError(
                        f"TikTok did not return a profile for @{username}: {blocked}"
                        if blocked
                        else f"TikTok user @{username} was not found or is not public"
                    )

            return Profile(
                username=user.get("uniqueId") or username,
                nickname=user.get("nickname") or "",
                bio=user.get("signature") or "",
                verified=bool(user.get("verified")),
                follower_count=_to_count(stats.get("followerCount")),
                following_count=_to_count(stats.get("followingCount")),
                like_count=_to_count(stats.get("heartCount")),
                video_count=_to_count(stats.get("videoCount")),
                avatar_url=user.get("avatarLarger") or user.get("avatarMedium") or "",
            )

        profile, _ = await self._cache.get_or_load(f"profile:{username.lower()}", load)
        return profile

    async def get_videos(self, username: str, count: int) -> VideoList:
        links, note = await self._cached_grid(f"videos:{username.lower()}:{count}", f"{BASE_URL}/@{username}")
        # Profile pages also show suggested videos from other accounts.
        own = [v for v in links if v["username"].lower() == username.lower()][:count]
        if not own and note is None:
            note = "No videos found (account is private, empty, or TikTok hid the grid)."
        return VideoList(username=username, count=len(own), videos=[_to_summary(v) for v in own], note=note)

    async def search_videos(self, query: str, count: int) -> SearchResults:
        links, note = await self._cached_grid(f"search:{query.lower()}:{count}", _search_url(query))
        results = [_to_summary(v) for v in links[:count]]
        return SearchResults(query=query, count=len(results), results=results, note=_note(note, results))

    async def discover_creators(self, topic: str, count: int) -> CreatorList:
        links, note = await self._cached_grid(
            f"creators:{topic.lower()}:{count}", _search_url(f"#{topic.lstrip('#')}")
        )
        creators: dict[str, Creator] = {}
        for v in links:
            if len(creators) >= count:
                break
            creators.setdefault(
                v["username"],
                Creator(
                    username=v["username"],
                    url=f"{BASE_URL}/@{v['username']}",
                    latest_video=v["title"][:80],
                ),
            )
        found = list(creators.values())
        return CreatorList(topic=topic, count=len(found), creators=found, note=_note(note, found))

    async def get_comments(self, video_url: str, count: int) -> CommentList:
        async def load() -> CommentList:
            async with self._browser.page() as page:
                note = await self._visit(page, video_url)
                comments = [] if note else await self._comments(page, count)

            return CommentList(
                video_url=video_url,
                count=len(comments),
                comments=comments,
                note=note
                or (
                    None
                    if comments
                    else "Comments could not be loaded; TikTok often hides them from logged-out browsers."
                ),
            )

        result, _ = await self._cache.get_or_load(f"comments:{video_url}:{count}", load)
        return result

    async def _comments(self, page: Page, count: int) -> list[Comment]:
        """Open the comment panel and read what rendered."""
        icon = await page.query_selector('[data-e2e="comment-icon"]')
        if not icon:
            return []
        await icon.click()
        await self._wait_for(page, _JS_COMMENTS_READY)
        await page.wait_for_timeout(self._settings.settle_ms)
        return [Comment(**c) for c in await page.evaluate(_JS_COMMENTS, count)]

    async def _cached_grid(self, key: str, url: str) -> tuple[list[dict[str, str]], str | None]:
        """Read a video grid, reusing a recent read.

        Concurrent identical reads still share one page load, but a block or an
        empty grid is never cached: the next attempt has to be a fresh request.
        """
        grid, _ = await self._cache.get_or_load(
            key,
            lambda: self._video_links(url),
            cache_when=lambda result: bool(result[0]),
        )
        return grid
