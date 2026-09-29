"""transcribe_video: speech-to-text for a video's audio track."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated

import anyio
from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from tiktokmcp.app import get_app
from tiktokmcp.errors import tool_errors
from tiktokmcp.models import Transcript
from tiktokmcp.tools._params import VideoRef, read_only
from tiktokmcp.validation import build_video_url

STEPS = 3

Language = Annotated[
    str | None,
    Field(
        description="Optional ISO-639-1 language code (e.g. 'en', 'es') to skip auto-detection.",
        pattern=r"^[a-zA-Z]{2,3}$",
    ),
]


def register(mcp: MCPServer) -> None:
    @mcp.tool(annotations=read_only("Transcribe a TikTok video"))
    async def transcribe_video(video_url: VideoRef, ctx: Context, language: Language = None) -> Transcript:
        """Transcribe a TikTok video's speech with the server's speech-to-text API.
        Returns the full text, language, duration, and word-level timestamps when the API
        supports them. Takes 10-60 seconds."""
        app = get_app(ctx)
        transcriber = app.transcriber
        with tool_errors():
            url = build_video_url(video_url)
            transcriber.check_ready()

            # yt-dlp, ffmpeg, and the HTTP upload block, so each stage runs in a worker thread.
            with (
                anyio.fail_after(app.settings.transcribe_timeout_s),
                tempfile.TemporaryDirectory(prefix="tiktok-mcp-") as tmp,
            ):
                video, audio = Path(tmp, "video.mp4"), Path(tmp, "audio.mp3")

                await ctx.report_progress(0, STEPS, "Downloading video")
                await anyio.to_thread.run_sync(transcriber.download, url, video)

                await ctx.report_progress(1, STEPS, "Extracting audio")
                await anyio.to_thread.run_sync(transcriber.extract_audio, video, audio)

                await ctx.report_progress(2, STEPS, "Transcribing")
                result = await anyio.to_thread.run_sync(transcriber.transcribe, audio, language)

                await ctx.report_progress(3, STEPS, "Done")

            return Transcript(
                video_url=url,
                model=transcriber.model,
                text=result.text,
                language=result.language,
                duration=result.duration,
                words=result.words,
            )
