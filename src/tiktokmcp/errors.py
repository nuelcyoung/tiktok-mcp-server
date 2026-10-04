"""Domain errors and their translation into MCP tool errors.

Services raise plain domain exceptions. The tool layer wraps each call in
``tool_errors()`` so anticipated failures reach the model as ``isError: true``
results with a readable message, instead of the SDK's generic
"Error executing tool" that it uses for unexpected crashes.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from mcp.server.mcpserver.exceptions import ToolError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


class TikTokMCPError(Exception):
    """Base class for failures the server anticipates."""


class NotFoundError(TikTokMCPError):
    """The requested user or video does not exist or is not public."""


class ConfigurationError(TikTokMCPError):
    """A required setting or external binary is missing."""


class UpstreamError(TikTokMCPError):
    """TikTok, yt-dlp, ffmpeg, or the transcription API failed in a way we can describe."""


class RateLimitedError(TikTokMCPError):
    """TikTok refused the request for rate-limit reasons."""


@contextmanager
def tool_errors() -> Iterator[None]:
    """Convert anticipated exceptions into ``ToolError`` for the client."""
    try:
        yield
    except ToolError:
        raise
    except (TikTokMCPError, ValueError) as exc:
        raise ToolError(str(exc)) from exc
    except PlaywrightTimeoutError as exc:
        raise ToolError(
            "TikTok did not respond in time. It may be rate-limiting this IP; retry shortly."
        ) from exc
    except TimeoutError as exc:
        raise ToolError("The operation timed out.") from exc
