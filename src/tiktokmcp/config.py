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

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            transcribe_api_url=os.environ.get("TRANSCRIBE_API_URL") or None,
            transcribe_api_key=os.environ.get("TRANSCRIBE_API_KEY") or None,
            transcribe_model=os.environ.get("TRANSCRIBE_MODEL") or "whisper-large-v3",
            ffmpeg_path=os.environ.get("FFMPEG_PATH") or None,
            headless=_env_bool("TIKTOK_MCP_HEADLESS", True),
            log_level=os.environ.get("TIKTOK_MCP_LOG_LEVEL", "INFO").upper(),
        )
