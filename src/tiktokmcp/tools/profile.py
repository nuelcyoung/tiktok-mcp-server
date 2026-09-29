"""get_profile: a user's public profile and stats."""

from __future__ import annotations

from mcp.server.mcpserver import Context, MCPServer

from tiktokmcp.app import get_app
from tiktokmcp.errors import tool_errors
from tiktokmcp.models import Profile
from tiktokmcp.tools._params import Username, read_only
from tiktokmcp.validation import sanitize_username


def register(mcp: MCPServer) -> None:
    @mcp.tool(annotations=read_only("Get TikTok profile"))
    async def get_profile(username: Username, ctx: Context) -> Profile:
        """Get a TikTok user's public profile: nickname, bio, verified status, follower,
        following, like, and video counts, and avatar URL."""
        with tool_errors():
            return await get_app(ctx).scraper.get_profile(sanitize_username(username))
