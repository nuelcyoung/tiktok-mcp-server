"""get_videos: recent videos from a user's profile grid."""

from __future__ import annotations

from mcp.server.mcpserver import Context, MCPServer

from tiktokmcp.app import get_app
from tiktokmcp.errors import tool_errors
from tiktokmcp.models import VideoList
from tiktokmcp.tools._params import Count, Username, read_only
from tiktokmcp.validation import sanitize_username


def register(mcp: MCPServer) -> None:
    @mcp.tool(annotations=read_only("List a TikTok user's videos"))
    async def get_videos(username: Username, ctx: Context, count: Count = 10) -> VideoList:
        """List a TikTok user's most recent public videos with id, caption, URL, and view count.
        Returns an empty list with a note if the account is private or TikTok blocks the request."""
        with tool_errors():
            return await get_app(ctx).scraper.get_videos(sanitize_username(username), count)
