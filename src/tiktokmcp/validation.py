"""Input normalization shared by the tools.

Numeric bounds (``count``) are enforced by the tool input schemas; these
helpers cover what JSON Schema can't express cleanly.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# TikTok handles: 1-24 chars of letters, digits, underscore, or dot.
USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,24}$")
# TikTok post ids are long numeric strings (typically 19 digits).
VIDEO_ID_RE = re.compile(r"^\d{6,25}$")
# Path form: @user/video/1234567890 (or /photo/).
VIDEO_PATH_RE = re.compile(r"^@?[A-Za-z0-9._]{1,24}/(?:video|photo)/\d{6,25}$")


def sanitize_username(username: str) -> str:
    """Strip a leading '@' and reject anything that isn't a plausible TikTok handle."""
    handle = (username or "").strip().lstrip("@")
    if not USERNAME_RE.fullmatch(handle):
        raise ValueError(f"Invalid TikTok username: {username!r}")
    return handle


def is_tiktok_host(host: str | None) -> bool:
    """True for tiktok.com and any subdomain (www, m, vm, vt, ...)."""
    normalized = (host or "").lower()
    return normalized == "tiktok.com" or normalized.endswith(".tiktok.com")


def require_tiktok_url(url: str) -> None:
    """Reject non-TikTok URLs so downloads can't be pointed at arbitrary hosts."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not is_tiktok_host(parsed.hostname):
        raise ValueError(f"URL must be an http(s) tiktok.com URL, got: {url!r}")


def build_video_url(value: str) -> str:
    """Resolve a video reference into a full tiktok.com URL.

    Accepts a full URL (including vm/vt short links), '@user/video/123',
    'user/video/123', or a bare numeric id (canonicalized via TikTok's
    '@i' placeholder handle, which redirects to the real author).
    """
    raw = (value or "").strip()
    if not raw:
        raise ValueError("Video reference is empty")

    if raw.startswith(("http://", "https://")):
        require_tiktok_url(raw)
        return raw

    path = raw if raw.startswith("@") else f"@{raw}"
    if VIDEO_PATH_RE.fullmatch(path):
        return f"https://www.tiktok.com/{path}"

    if VIDEO_ID_RE.fullmatch(raw):
        return f"https://www.tiktok.com/@i/video/{raw}"

    raise ValueError("Expected a tiktok.com video URL, '@user/video/id', or a numeric video id")
