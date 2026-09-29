"""Typed tool results.

Returning these models (instead of JSON strings) lets the SDK publish an
``outputSchema`` for every tool and send ``structuredContent`` alongside the
text fallback, which is what current MCP clients expect.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Profile(BaseModel):
    username: str
    nickname: str
    bio: str = ""
    verified: bool = False
    follower_count: int | None = None
    following_count: int | None = None
    like_count: int | None = None
    video_count: int | None = None
    avatar_url: str = ""


class VideoSummary(BaseModel):
    id: str
    title: str
    url: str
    creator: str
    views: str = Field(description="View count as TikTok displays it, e.g. '1.2M'.")


class VideoList(BaseModel):
    username: str
    count: int
    videos: list[VideoSummary]
    note: str | None = None


class SearchResults(BaseModel):
    query: str
    count: int
    results: list[VideoSummary]
    note: str | None = None


class Creator(BaseModel):
    username: str
    url: str
    latest_video: str = Field(description="Title of the video that surfaced this creator.")


class CreatorList(BaseModel):
    topic: str
    count: int
    creators: list[Creator]
    note: str | None = None


class Comment(BaseModel):
    author: str
    text: str
    likes: str = Field(description="Like count as TikTok displays it.")


class CommentList(BaseModel):
    video_url: str
    count: int
    comments: list[Comment]
    note: str | None = None


class TranscriptWord(BaseModel):
    word: str
    start: float = Field(description="Seconds from the start of the audio.")
    end: float


class Transcript(BaseModel):
    video_url: str
    model: str = Field(description="Speech-to-text model that produced this transcript.")
    text: str
    language: str
    duration: float = Field(description="Audio duration in seconds.")
    words: list[TranscriptWord]
