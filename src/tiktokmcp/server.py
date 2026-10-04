"""MCP server factory and command-line entry point."""

from __future__ import annotations

import argparse
import contextlib
import logging
import sys

from mcp.server.mcpserver import MCPServer

from tiktokmcp import __version__
from tiktokmcp.app import AppContext, make_lifespan
from tiktokmcp.config import Settings
from tiktokmcp.tools import register_tools

INSTRUCTIONS = """\
Read-only access to public TikTok data via a headless browser.

- Start with search_videos or discover_creators to find content, then get_profile / get_videos
  for a specific account, and get_comments or transcribe_video for a specific video.
- Video tools accept a full URL, '@user/video/<id>', or a bare numeric id.
- Each browser call takes several seconds; transcribe_video can take up to a minute.
- Counts such as views and likes in listings are TikTok's display strings (e.g. '1.2M').
- Empty results come with a `note` when TikTok blocked or hid the data; do not retry immediately.
- Requests are paced and identical reads are cached, so a retry right after a block adds nothing:
  when a `note` says TikTok is rate-limiting, wait or gather other data instead of calling again.
"""


def create_server(settings: Settings | None = None) -> MCPServer[AppContext]:
    settings = settings or Settings.from_env()
    mcp = MCPServer(
        name="tiktok-mcp",
        title="TikTok",
        version=__version__,
        instructions=INSTRUCTIONS,
        log_level=settings.log_level,  # type: ignore[arg-type]
        lifespan=make_lifespan(settings),
    )
    register_tools(mcp)
    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tiktok-mcp", description="TikTok MCP server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host for streamable-http")
    parser.add_argument("--port", type=int, default=8000, help="Bind port for streamable-http")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    # stdout carries the JSON-RPC stream on stdio, so all logging goes to stderr.
    logging.basicConfig(
        level=settings.log_level,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.transport == "stdio":
        # Windows defaults these streams to a local codepage, which cannot encode
        # the emoji and non-Latin bios TikTok profiles are full of.
        for stream in (sys.stdout, sys.stderr):
            with contextlib.suppress(AttributeError, ValueError):  # type: ignore[attr-defined]
                stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    mcp = create_server(settings)
    if args.transport == "stdio":
        mcp.run("stdio")
    else:
        mcp.run("streamable-http", host=args.host, port=args.port)
