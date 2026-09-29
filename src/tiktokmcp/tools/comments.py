"""get_comments: top-level comments on a video."""

from __future__ import annotations

from mcp.server.mcpserver import Context, MCPServer

from tiktokmcp.app import get_app
from tiktokmcp.errors import tool_errors
from tiktokmcp.models import CommentList
from tiktokmcp.tools._params import Count, VideoRef, read_only
from tiktokmcp.validation import build_video_url


def register(mcp: MCPServer) -> None:
    @mcp.tool(annotations=read_only("Get TikTok video comments"))
    async def get_comments(video_id: VideoRef, ctx: Context, count: Count = 20) -> CommentList:
        """Get top-level comments on a TikTok video (author, text, likes).
        An empty list comes with a note when TikTok hides comments from logged-out browsers."""
        with tool_errors():
            return await get_app(ctx).scraper.get_comments(build_video_url(video_id), count)
