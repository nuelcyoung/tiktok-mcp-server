"""TikTok page scraping: profile JSON, video grids, search results, comments."""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from tiktokmcp.browser import BrowserManager
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

logger = logging.getLogger(__name__)

BASE_URL = "https://www.tiktok.com"

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
    || document.body.innerText.includes("went wrong")
    || document.body.innerText.includes("find this account")"""

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


BLOCKED_NOTE = (
    "TikTok returned an error page; it is likely rate-limiting or blocking this IP. Try again later."
)
EMPTY_NOTE = "No results found."


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_summary(raw: dict[str, str]) -> VideoSummary:
    return VideoSummary(
        id=raw["id"],
        title=raw["title"][:150],
        url=f"{BASE_URL}/@{raw['username']}/video/{raw['id']}",
        creator=raw["username"],
        views=raw["views"],
    )


class TikTokScraper:
    def __init__(self, browser: BrowserManager, settings: Settings) -> None:
        self._browser = browser
        self._settings = settings

    async def _goto(self, page: Page, url: str) -> None:
        await page.goto(url, wait_until="domcontentloaded", timeout=self._settings.navigation_timeout_ms)

    async def _wait_for(self, page: Page, predicate: str) -> None:
        """Best-effort wait: an empty page is a valid (empty) result, not an error."""
        try:
            await page.wait_for_function(predicate, timeout=self._settings.render_timeout_ms)
        except PlaywrightTimeoutError:
            logger.debug("Render wait timed out on %s", page.url)

    async def _video_links(self, url: str) -> tuple[list[dict[str, str]], str | None]:
        """Return the page's video links and, when there are none, a note saying why."""
        async with self._browser.page() as page:
            await self._goto(page, url)
            await self._wait_for(page, _JS_GRID_READY)
            await page.wait_for_timeout(3_000)
            links = await page.evaluate(_JS_VIDEO_LINKS)
            blocked = not links and "went wrong" in await page.evaluate("document.body.innerText")
        return links, (BLOCKED_NOTE if blocked else None)

    async def get_profile(self, username: str) -> Profile:
        async with self._browser.page() as page:
            await self._goto(page, f"{BASE_URL}/@{username}")
            args = {"scope": "webapp.user-detail"}
            user = await page.evaluate(_JS_UNIVERSAL_DATA, {**args, "path": "userInfo.user"})
            stats = await page.evaluate(_JS_UNIVERSAL_DATA, {**args, "path": "userInfo.stats"}) or {}

        if not user:
            raise NotFoundError(f"TikTok user @{username} was not found or is not public")

        return Profile(
            username=user.get("uniqueId") or username,
            nickname=user.get("nickname") or "",
            bio=user.get("signature") or "",
            verified=bool(user.get("verified")),
            follower_count=_to_int(stats.get("followerCount")),
            following_count=_to_int(stats.get("followingCount")),
            like_count=_to_int(stats.get("heartCount")),
            video_count=_to_int(stats.get("videoCount")),
            avatar_url=user.get("avatarLarger") or user.get("avatarMedium") or "",
        )

    async def get_videos(self, username: str, count: int) -> VideoList:
        links, note = await self._video_links(f"{BASE_URL}/@{username}")
        # Profile pages also show suggested videos from other accounts.
        own = [v for v in links if v["username"].lower() == username.lower()][:count]
        if not own and note is None:
            note = "No videos found (account is private, empty, or TikTok hid the grid)."
        return VideoList(username=username, count=len(own), videos=[_to_summary(v) for v in own], note=note)

    async def search_videos(self, query: str, count: int) -> SearchResults:
        links, note = await self._video_links(_search_url(query))
        results = [_to_summary(v) for v in links[:count]]
        return SearchResults(
            query=query, count=len(results), results=results, note=note or (None if results else EMPTY_NOTE)
        )

    async def discover_creators(self, topic: str, count: int) -> CreatorList:
        links, note = await self._video_links(_search_url(f"#{topic.lstrip('#')}"))
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
        return CreatorList(
            topic=topic,
            count=len(creators),
            creators=list(creators.values()),
            note=note or (None if creators else EMPTY_NOTE),
        )

    async def get_comments(self, video_url: str, count: int) -> CommentList:
        async with self._browser.page() as page:
            await self._goto(page, video_url)
            await page.wait_for_timeout(2_000)
            icon = await page.query_selector('[data-e2e="comment-icon"]')
            if icon:
                await icon.click()
                await self._wait_for(page, _JS_COMMENTS_READY)
            raw = await page.evaluate(_JS_COMMENTS, count)

        comments = [Comment(**c) for c in raw]
        return CommentList(
            video_url=video_url,
            count=len(comments),
            comments=comments,
            note=None
            if comments
            else "Comments could not be loaded; TikTok often hides them from logged-out browsers.",
        )
