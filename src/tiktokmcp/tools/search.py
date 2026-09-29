"""search_videos: keyword or hashtag search."""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from tiktokmcp.app import get_app
from tiktokmcp.errors import tool_errors
from tiktokmcp.models import SearchResults
from tiktokmcp.tools._params import Count, read_only

Query = Annotated[
    str,
    Field(
        description="Search terms. Prefix with '#' to search a hashtag (e.g. '#booktok').",
        min_length=1,
        max_length=200,
    ),
]


def register(mcp: MCPServer) -> None:
    @mcp.tool(annotations=read_only("Search TikTok videos"))
    async def search_videos(query: Query, ctx: Context, count: Count = 10) -> SearchResults:
        """Search TikTok videos by keyword or hashtag. Returns id, caption, URL, creator, and view count."""
        with tool_errors():
            return await get_app(ctx).scraper.search_videos(query.strip(), count)
