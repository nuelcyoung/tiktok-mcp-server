"""Protocol-level tests against the real server over the SDK's in-memory transport.

None of these reach tiktok.com: they cover discovery metadata and the
validation paths that fail before the browser is launched.
"""

from __future__ import annotations

import pytest
from mcp import Client

from tiktokmcp.config import Settings
from tiktokmcp.server import create_server

EXPECTED_TOOLS = {
    "get_profile",
    "get_videos",
    "get_comments",
    "search_videos",
    "discover_creators",
    "transcribe_video",
}

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client():
    async with Client(create_server(Settings())) as c:
        yield c


async def test_lists_all_tools(client: Client) -> None:
    tools = (await client.list_tools()).tools
    assert {t.name for t in tools} == EXPECTED_TOOLS


async def test_tools_are_fully_described(client: Client) -> None:
    for tool in (await client.list_tools()).tools:
        assert tool.description, tool.name
        assert tool.output_schema, f"{tool.name} has no outputSchema"
        assert "ctx" not in tool.input_schema.get("properties", {}), tool.name
        for name, prop in tool.input_schema["properties"].items():
            assert prop.get("description"), f"{tool.name}.{name} has no description"

        ann = tool.annotations
        assert ann is not None and ann.title, tool.name
        assert ann.read_only_hint is True
        assert ann.destructive_hint is False
        assert ann.open_world_hint is True


async def test_count_is_bounded_in_schema(client: Client) -> None:
    tool = next(t for t in (await client.list_tools()).tools if t.name == "get_videos")
    count = tool.input_schema["properties"]["count"]
    assert (count["minimum"], count["maximum"], count["default"]) == (1, 50, 10)


async def test_invalid_username_is_a_tool_error(client: Client) -> None:
    result = await client.call_tool("get_profile", {"username": "not a valid handle!"})
    assert result.is_error
    assert "Invalid TikTok username" in result.content[0].text


async def test_out_of_range_count_is_rejected(client: Client) -> None:
    result = await client.call_tool("search_videos", {"query": "cats", "count": 500})
    assert result.is_error


async def test_non_tiktok_url_is_rejected(client: Client) -> None:
    result = await client.call_tool("get_comments", {"video_id": "https://example.com/video/123"})
    assert result.is_error
    assert "tiktok.com" in result.content[0].text


async def test_transcribe_without_api_url_explains_setup(client: Client) -> None:
    result = await client.call_tool("transcribe_video", {"video_url": "7300000000000000000"})
    assert result.is_error
    assert "TRANSCRIBE_API_URL" in result.content[0].text
