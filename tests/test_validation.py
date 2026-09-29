from __future__ import annotations

import pytest

from tiktokmcp.validation import build_video_url, sanitize_username


@pytest.mark.parametrize(("raw", "expected"), [("@khaby.lame", "khaby.lame"), ("  user_1 ", "user_1")])
def test_sanitize_username(raw: str, expected: str) -> None:
    assert sanitize_username(raw) == expected


@pytest.mark.parametrize("raw", ["", "@", "has space", "a" * 25, "bad/slash"])
def test_sanitize_username_rejects(raw: str) -> None:
    with pytest.raises(ValueError):
        sanitize_username(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "https://www.tiktok.com/@a/video/7300000000000000000",
            "https://www.tiktok.com/@a/video/7300000000000000000",
        ),
        ("https://vm.tiktok.com/ZMabc123/", "https://vm.tiktok.com/ZMabc123/"),
        ("@a/video/7300000000000000000", "https://www.tiktok.com/@a/video/7300000000000000000"),
        ("a/photo/7300000000000000000", "https://www.tiktok.com/@a/photo/7300000000000000000"),
        ("7300000000000000000", "https://www.tiktok.com/@i/video/7300000000000000000"),
    ],
)
def test_build_video_url(raw: str, expected: str) -> None:
    assert build_video_url(raw) == expected


@pytest.mark.parametrize(
    "raw", ["", "https://evil.com/@a/video/1234567", "https://tiktok.com.evil.com/x", "hello"]
)
def test_build_video_url_rejects(raw: str) -> None:
    with pytest.raises(ValueError):
        build_video_url(raw)
