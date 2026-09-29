"""Transcription pipeline: yt-dlp download -> ffmpeg audio -> speech-to-text API.

The API is any OpenAI-compatible ``POST /audio/transcriptions`` endpoint, so
Groq, OpenAI, and self-hosted Whisper servers all work with a URL and a key.
Each stage is synchronous and exposed separately so the tool can run them in
a worker thread and report progress between stages.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yt_dlp

from tiktokmcp.config import Settings
from tiktokmcp.errors import ConfigurationError, UpstreamError
from tiktokmcp.models import TranscriptWord
from tiktokmcp.validation import require_tiktok_url

logger = logging.getLogger(__name__)

ENDPOINT_PATH = "/audio/transcriptions"


def transcription_endpoint(api_url: str) -> str:
    """Accept a base URL (``.../v1``) or the full ``.../audio/transcriptions`` endpoint."""
    url = api_url.rstrip("/")
    return url if url.endswith(ENDPOINT_PATH) else url + ENDPOINT_PATH


@dataclass(slots=True)
class TranscriptionResult:
    text: str
    language: str
    duration: float
    words: list[TranscriptWord] = field(default_factory=list)


def find_ffmpeg(configured: str | None) -> str:
    """FFMPEG_PATH if set, else ffmpeg on PATH, else the binary bundled with imageio-ffmpeg."""
    if configured:
        if shutil.which(configured) is None:
            raise ConfigurationError(f"FFMPEG_PATH points to {configured!r}, which is not an executable.")
        return configured
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


class Transcriber:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.Client(timeout=httpx.Timeout(300, connect=15))

    @property
    def model(self) -> str:
        return self._settings.transcribe_model

    def check_ready(self) -> None:
        """Fail fast, before downloading anything, if configuration is missing."""
        if not self._settings.transcribe_api_url:
            raise ConfigurationError(
                "TRANSCRIBE_API_URL is not set. Add TRANSCRIBE_API_URL and TRANSCRIBE_API_KEY to this "
                "server's env block (any OpenAI-compatible endpoint, e.g. https://api.groq.com/openai/v1)."
            )
        find_ffmpeg(self._settings.ffmpeg_path)

    def download(self, url: str, dest: Path) -> None:
        require_tiktok_url(url)
        limit = self._settings.max_download_bytes
        opts = {
            "format": "best[ext=mp4]/best",
            "outtmpl": str(dest),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "socket_timeout": 30,
            "retries": 3,
            "max_filesize": limit,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except yt_dlp.utils.DownloadError as exc:
            raise UpstreamError(f"Could not download the video: {exc}") from exc

        if not dest.exists():
            raise UpstreamError(
                "yt-dlp finished without producing a file (the video may exceed the size cap)"
            )
        if dest.stat().st_size > limit:
            raise UpstreamError(f"Video exceeds the {limit // (1024 * 1024)} MB download cap")

    def extract_audio(self, video: Path, audio: Path) -> None:
        cmd = [
            find_ffmpeg(self._settings.ffmpeg_path),
            "-i",
            str(video),
            "-vn",
            "-ac",
            "1",
            "-b:a",
            "64k",
            "-y",
            str(audio),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=self._settings.ffmpeg_timeout_s)
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or b"").decode("utf-8", errors="replace")
            raise UpstreamError(f"ffmpeg exited with code {exc.returncode}: {stderr[-500:]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise UpstreamError(f"ffmpeg timed out after {self._settings.ffmpeg_timeout_s:.0f}s") from exc

    def _post(self, audio: Path, fields: dict[str, Any]) -> httpx.Response:
        key = self._settings.transcribe_api_key
        with audio.open("rb") as f:
            try:
                return self._client.post(
                    transcription_endpoint(self._settings.transcribe_api_url or ""),
                    headers={"Authorization": f"Bearer {key}"} if key else {},
                    data=fields,
                    files={"file": (audio.name, f, "audio/mpeg")},
                )
            except httpx.RequestError as exc:
                raise UpstreamError(f"Could not reach the transcription API: {exc}") from exc

    def transcribe(self, audio: Path, language: str | None = None) -> TranscriptionResult:
        fields: dict[str, Any] = {
            "model": self.model,
            "response_format": "verbose_json",
            "timestamp_granularities[]": ["word"],
        }
        if language:
            fields["language"] = language

        response = self._post(audio, fields)
        if response.status_code == 400:
            # Some models and servers only support plain JSON (no word timestamps).
            logger.info("Transcription API rejected verbose_json; retrying with json")
            fields["response_format"] = "json"
            del fields["timestamp_granularities[]"]
            response = self._post(audio, fields)

        if response.status_code in (401, 403):
            raise ConfigurationError(
                f"The transcription API rejected TRANSCRIBE_API_KEY (HTTP {response.status_code})."
            )
        if not response.is_success:
            raise UpstreamError(
                f"Transcription API returned HTTP {response.status_code}: {response.text[:300]}"
            )

        body = response.json()
        words = [
            TranscriptWord(
                word=w.get("word", ""),
                start=round(float(w.get("start") or 0), 3),
                end=round(float(w.get("end") or 0), 3),
            )
            for w in body.get("words") or []
        ]
        duration = body.get("duration") or (words[-1].end if words else 0)
        return TranscriptionResult(
            text=(body.get("text") or "").strip(),
            language=body.get("language") or language or "unknown",
            duration=round(float(duration), 2),
            words=words,
        )
