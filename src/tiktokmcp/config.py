"""Server settings, read once from the environment the MCP client provides.

No .env file is read: MCP clients inject configuration through the server's
``env`` block, so that is the single source of truth.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


@dataclass(frozen=True, slots=True)
class Settings:
    # Any OpenAI-compatible speech-to-text endpoint (Groq, OpenAI, self-hosted Whisper, ...).
    transcribe_api_url: str | None = None
    transcribe_api_key: str | None = None
    transcribe_model: str = "whisper-large-v3"
    ffmpeg_path: str | None = None  # None: PATH, then the bundled imageio-ffmpeg binary
    headless: bool = True
    log_level: str = "INFO"

    # Hard limits that protect the host from runaway work.
    max_download_bytes: int = 100 * 1024 * 1024
    ffmpeg_timeout_s: float = 120
    transcribe_timeout_s: float = 600
    navigation_timeout_ms: int = 30_000
    render_timeout_ms: int = 15_000

    # How politely we hit tiktok.com. Defaults follow a person browsing: a few
    # seconds between page loads, a few dozen pages per five minutes, and an
    # exponential cooldown the moment TikTok pushes back (see throttle.py).
    min_interval_s: float = 4.0
    max_requests_per_window: int = 24
    request_window_s: float = 300.0
    cooldown_base_s: float = 90.0
    cooldown_max_s: float = 900.0

    # How long a page is given to finish rendering before we read it.
    settle_ms: int = 2_500

    # Repeats of the same read are served from memory instead of re-requested.
    cache_ttl_s: float = 300.0

    # Browser identity. A persistent profile keeps TikTok's cookies across
    # calls and restarts, which is what makes repeat visits look like the same
    # person; ``channel`` picks an installed Chrome/Edge over bundled Chromium.
    persist_profile: bool = True
    profile_dir: str | None = None
    browser_channel: str | None = None  # None: auto (chrome, msedge, chromium, bundled)
    block_telemetry: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        channel = (os.environ.get("TIKTOK_MCP_CHANNEL") or "").strip()
        return cls(
            transcribe_api_url=os.environ.get("TRANSCRIBE_API_URL") or None,
            transcribe_api_key=os.environ.get("TRANSCRIBE_API_KEY") or None,
            transcribe_model=os.environ.get("TRANSCRIBE_MODEL") or "whisper-large-v3",
            ffmpeg_path=os.environ.get("FFMPEG_PATH") or None,
            headless=_env_bool("TIKTOK_MCP_HEADLESS", True),
            log_level=os.environ.get("TIKTOK_MCP_LOG_LEVEL", "INFO").upper(),
            min_interval_s=_env_float("TIKTOK_MCP_MIN_INTERVAL_S", 4.0),
            max_requests_per_window=_env_int("TIKTOK_MCP_REQUESTS_PER_WINDOW", 24),
            request_window_s=_env_float("TIKTOK_MCP_WINDOW_S", 300.0),
            cooldown_base_s=_env_float("TIKTOK_MCP_COOLDOWN_S", 90.0),
            cooldown_max_s=_env_float("TIKTOK_MCP_COOLDOWN_MAX_S", 900.0),
            settle_ms=_env_int("TIKTOK_MCP_SETTLE_MS", 2_500),
            cache_ttl_s=_env_float("TIKTOK_MCP_CACHE_TTL_S", 300.0),
            persist_profile=_env_bool("TIKTOK_MCP_PERSIST_PROFILE", True),
            profile_dir=os.environ.get("TIKTOK_MCP_PROFILE_DIR") or None,
            browser_channel=channel or None,
            block_telemetry=_env_bool("TIKTOK_MCP_BLOCK_TELEMETRY", True),
        )
