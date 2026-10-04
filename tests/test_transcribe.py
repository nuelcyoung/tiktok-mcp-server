"""Transcription API client tests, using httpx's mock transport (no network)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tiktokmcp.config import Settings
from tiktokmcp.errors import ConfigurationError
from tiktokmcp.transcribe import Transcriber

VERBOSE = {
    "text": " hello world ",
    "language": "english",
    "duration": 1.5,
    "words": [{"word": "hello", "start": 0.0, "end": 0.5}, {"word": "world", "start": 0.6, "end": 1.1}],
}


@pytest.fixture
def audio(tmp_path: Path) -> Path:
    path = tmp_path / "audio.mp3"
    path.write_bytes(b"fake mp3")
    return path


def make(handler, **settings) -> Transcriber:
    defaults = {"transcribe_api_url": "https://stt.example/v1/audio/transcriptions", "transcribe_api_key": "sk-test"}
    return Transcriber(
        Settings(**{**defaults, **settings}), client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_url_is_used_verbatim(audio: Path) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"text": "ok"})

    url = "https://stt.example/custom/path"
    make(handler, transcribe_api_url=url).transcribe(audio)
    assert seen == [url]


def test_sends_key_model_and_parses_words(audio: Path) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=VERBOSE)

    result = make(handler, transcribe_model="whisper-1").transcribe(audio, language="en")

    request = seen[0]
    body = request.read().decode(errors="replace")
    assert str(request.url) == "https://stt.example/v1/audio/transcriptions"
    assert request.headers["Authorization"] == "Bearer sk-test"
    assert "whisper-1" in body and "verbose_json" in body and 'name="language"' in body
    assert result.text == "hello world"
    assert result.language == "english"
    assert result.duration == 1.5
    assert [w.word for w in result.words] == ["hello", "world"]


def test_falls_back_to_json_when_verbose_rejected(audio: Path) -> None:
    formats: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode(errors="replace")
        verbose = "verbose_json" in body
        formats.append("verbose_json" if verbose else "json")
        if verbose:
            return httpx.Response(400, json={"error": "unsupported response_format"})
        return httpx.Response(200, content=json.dumps({"text": "hi"}))

    result = make(handler).transcribe(audio)
    assert formats == ["verbose_json", "json"]
    assert (result.text, result.words, result.duration) == ("hi", [], 0)


def test_no_key_sends_no_auth_header(audio: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "Authorization" not in request.headers
        return httpx.Response(200, json={"text": "ok"})

    assert make(handler, transcribe_api_key=None).transcribe(audio).text == "ok"


def test_rejected_key_is_a_configuration_error(audio: Path) -> None:
    transcriber = make(lambda _: httpx.Response(401, json={"error": "bad key"}))
    with pytest.raises(ConfigurationError, match="TRANSCRIBE_API_KEY"):
        transcriber.transcribe(audio)


def test_check_ready_requires_url() -> None:
    with pytest.raises(ConfigurationError, match="TRANSCRIBE_API_URL"):
        Transcriber(Settings()).check_ready()
