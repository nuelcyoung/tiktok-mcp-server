"""discover_creators: unique creators posting under a topic."""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from tiktokmcp.app import get_app
from tiktokmcp.errors import tool_errors
from tiktokmcp.models import CreatorList
from tiktokmcp.tools._params import Count, read_only

Topic = Annotated[
    str,
    Field(
        description="Topic or hashtag, with or without '#' (e.g. 'skincare').",
        min_length=1,
        max_length=100,
    ),
]


def register(mcp: MCPServer) -> None:
    @mcp.tool(annotations=read_only("Discover TikTok creators"))
    async def discover_creators(topic: Topic, ctx: Context, count: Count = 10) -> CreatorList:
        """Find TikTok creators posting about a topic. Searches the topic as a hashtag and
        returns unique creators with their profile URL and the video that surfaced them."""
        with tool_errors():
            tag = topic.strip().lstrip("#")
            if not tag:
                raise ValueError("topic must contain more than '#'")
            return await get_app(ctx).scraper.discover_creators(tag, count)
