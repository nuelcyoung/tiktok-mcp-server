"""Tool registration. Each module exposes ``register(mcp)`` for one tool."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from tiktokmcp.tools import comments, discover, profile, search, transcript, videos


def register_tools(mcp: MCPServer) -> None:
    for module in (profile, videos, comments, search, discover, transcript):
        module.register(mcp)
