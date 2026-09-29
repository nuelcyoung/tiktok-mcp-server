"""Shared parameter types and annotations so every tool schema is self-describing."""

from __future__ import annotations

from typing import Annotated

from mcp_types import ToolAnnotations
from pydantic import Field

MAX_COUNT = 50

Username = Annotated[
    str,
    Field(
        description="TikTok handle, with or without the leading '@' (e.g. 'khaby.lame').",
        min_length=1,
        max_length=25,
    ),
]

VideoRef = Annotated[
    str,
    Field(
        description=(
            "A TikTok video: full URL (tiktok.com, vm.tiktok.com short links accepted), "
            "'@user/video/<id>', or a bare numeric video id."
        ),
        min_length=1,
    ),
]

Count = Annotated[
    int,
    Field(description=f"Maximum number of items to return (1-{MAX_COUNT}).", ge=1, le=MAX_COUNT),
]


def read_only(title: str) -> ToolAnnotations:
    """Every tool only reads public data from tiktok.com, never changes it, and is safe to retry."""
    return ToolAnnotations(
        title=title,
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
