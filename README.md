# TikTok MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io) server that lets an AI agent read public TikTok data: **search**, **profiles**, **videos**, **discovery**, **comments**, and **transcription**.

There is no TikTok developer account to apply for and no OAuth flow. Everything comes off public pages, so the only credential you might enter is a key for your own transcription endpoint.

It runs on any MCP client (Claude, Cursor, opencode, Codex) and returns structured output (`structuredContent` + `outputSchema`) from every tool. Transcription works against any OpenAI-compatible speech-to-text endpoint: Groq, OpenAI, or a Whisper server you host yourself.

## Quick start

Paste this into your MCP client config. There is nothing to install first: [`uvx`](https://docs.astral.sh/uv/) fetches the package and runs it on the initial launch.

```json
{
  "mcpServers": {
    "tiktok": {
      "type": "stdio",
      "command": "uvx",
      "args": ["tiktok-mcp-server"],
      "env": {
        "TRANSCRIBE_API_URL": "https://api.groq.com/openai/v1",
        "TRANSCRIBE_API_KEY": "your-key"
      }
    }
  }
}
```

Things worth knowing before the first call:

- The `env` block exists only for `transcribe_video`. Write `"env": {}` if you want the other five tools and nothing else. The endpoint must serve an OpenAI-compatible `POST /audio/transcriptions` route backed by a speech-to-text model such as `whisper-large-v3`.
- The first tool call downloads Playwright Chromium once, about 150 MB. ffmpeg ships with the package (`imageio-ffmpeg`); set `FFMPEG_PATH` if you'd rather use your own binary.
- You need [uv](https://docs.astral.sh/uv/getting-started/installation/) on the machine, since it provides `uvx`. Python 3.11+ comes along with it; uv installs that itself.
- **Linux only:** headless Chromium needs system libraries that `uvx` can't install for you. On a fresh machine or Docker image, run this once (it may prompt for `sudo`):

  ```bash
  uvx --from playwright playwright install-deps chromium
  ```

  Windows and macOS don't need this step.

### Running from a checkout (before PyPI)

Not on PyPI yet? Point `uvx` at a local checkout or at the git repo (use whichever fits):

```json
"args": ["--from", "C:\\path\\to\\tiktokmcp", "tiktok-mcp-server"]
```

```json
"args": ["--from", "git+https://github.com/<you>/tiktokmcp", "tiktok-mcp-server"]
```

## MCP tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `get_profile` | Profile info: bio, follower/following/like/video counts, verified status, avatar | `username` |
| `get_videos` | A user's recent videos with id, caption, URL, view count | `username`, `count` (default 10) |
| `get_comments` | Top-level comments: author, text, likes | `video_id`, `count` (default 20) |
| `search_videos` | Search by keyword or hashtag (`#booktok`) | `query`, `count` (default 10) |
| `discover_creators` | Creators posting about a topic/hashtag | `topic`, `count` (default 10) |
| `transcribe_video` | Download, extract audio, and transcribe via your speech-to-text API (reports progress) | `video_url`, `language` (optional) |

What the tools have in common:

- `count` is validated to 1–50 by the input schema; `username` accepts handles with or without `@`
- Video tools accept a full URL (including `vm.tiktok.com` / `vt.tiktok.com` short links), `@user/video/<id>`, or a bare numeric id
- Every tool is annotated `readOnlyHint`, `idempotentHint`, `openWorldHint`, `destructiveHint: false`
- Anticipated failures (bad input, user not found, missing `TRANSCRIBE_API_URL`, TikTok timeouts) come back as `isError: true` with a readable message
- When TikTok blocks or hides data, tools return an empty list plus a `note` instead of failing
- Each browser call takes several seconds; `transcribe_video` can take up to a minute. Counts like views/likes are TikTok's display strings (e.g. `1.2M`)

## Configuration

Your MCP client injects configuration as environment variables. The server never reads a `.env` file of its own.

| Variable | Required | Description |
|----------|----------|-------------|
| `TRANSCRIBE_API_URL` | For transcription | OpenAI-compatible base URL (`https://api.groq.com/openai/v1`, `https://api.openai.com/v1`, `http://localhost:8000/v1`) or the full `.../audio/transcriptions` URL |
| `TRANSCRIBE_API_KEY` | For transcription | API key for that endpoint (omit for keyless local servers) |
| `TRANSCRIBE_MODEL` | No | Model name (default `whisper-large-v3`; use `whisper-1` for OpenAI) |
| `FFMPEG_PATH` | No | Path to an ffmpeg binary (default: `ffmpeg` on PATH, else the bundled one) |
| `TIKTOK_MCP_HEADLESS` | No | `false` shows the browser while debugging (default `true`) |
| `TIKTOK_MCP_LOG_LEVEL` | No | `DEBUG`, `INFO` (default), `WARNING`, `ERROR` |

Built-in safety limits: 100 MB download cap, 120 s ffmpeg timeout, 600 s transcription timeout, 30 s navigation timeout.

## Client setup

Every client launches the same command, `uvx tiktok-mcp-server`. Only the config format differs.

### Claude Desktop / Claude Code / Cursor

```json
{
  "mcpServers": {
    "tiktok": {
      "type": "stdio",
      "command": "uvx",
      "args": ["tiktok-mcp-server"],
      "env": {
        "TRANSCRIBE_API_URL": "https://api.groq.com/openai/v1",
        "TRANSCRIBE_API_KEY": "your-key"
      }
    }
  }
}
```

Claude Code one-liner:

```bash
claude mcp add tiktok -e TRANSCRIBE_API_URL=... -e TRANSCRIBE_API_KEY=... -- uvx tiktok-mcp-server
```

### opencode (`~/.config/opencode/opencode.json` → `mcp`)

```json
"tiktok": {
  "type": "local",
  "command": ["uvx", "tiktok-mcp-server"],
  "environment": {
    "TRANSCRIBE_API_URL": "https://api.groq.com/openai/v1",
    "TRANSCRIBE_API_KEY": "your-key"
  },
  "enabled": true,
  "timeout": 120000
}
```

### Codex (`~/.codex/config.toml`)

```toml
[mcp_servers.tiktok]
command = "uvx"
args = ["tiktok-mcp-server"]

[mcp_servers.tiktok.env]
TRANSCRIBE_API_URL = "https://api.groq.com/openai/v1"
TRANSCRIBE_API_KEY = "your-key"
```

## Running manually

```bash
uvx tiktok-mcp-server                                          # stdio (what MCP clients launch)
uvx tiktok-mcp-server --transport streamable-http --host 127.0.0.1 --port 8000
```

Inspect it interactively with the MCP Inspector:

```bash
npx @modelcontextprotocol/inspector uvx tiktok-mcp-server
```

## How it works

- A real browser (**Playwright Chromium**) opens TikTok's public pages, just like you would — no API keys or developer accounts
- Profiles are read from the page's built-in data; search, discovery, and comments are read after the page finishes loading
- **Transcription**: download the video → trim it to a small audio file → send it to your speech-to-text API → return the text
- Logs go to stderr so the connection to your AI client stays clean

## Architecture

```
src/tiktokmcp/
├── __main__.py      # python -m tiktokmcp
├── server.py        # create_server() factory, instructions, CLI (--transport/--host/--port)
├── app.py           # lifespan + AppContext (browser, scraper, transcriber)
├── config.py        # Settings.from_env()
├── models.py        # Pydantic result models -> outputSchema / structuredContent
├── errors.py        # domain errors -> ToolError translation
├── validation.py    # username / video-reference normalization
├── browser.py       # BrowserManager: lazy Playwright Chromium, owned by the lifespan
├── scraper.py       # TikTokScraper: profile JSON, video grids, search, comments
├── transcribe.py    # Transcriber: yt-dlp -> ffmpeg -> speech-to-text API
└── tools/           # one module per tool, each exposing register(mcp)
    ├── _params.py   # shared Annotated parameter types + ToolAnnotations
    ├── profile.py  videos.py  comments.py
    └── search.py   discover.py  transcript.py
tests/               # pytest, in-memory MCP client (no network)
```

Tool functions are thin: they validate input, pull shared services from the lifespan context, and return a typed model. Scraping and transcription logic lives in services that know nothing about MCP.

## Development

```bash
uv sync                                              # install deps
uv run playwright install chromium                   # browser for the scraper
uv run pytest                                        # offline test suite
uv run ruff check src tests && uv run ruff format src tests
```


## Limitations

- Read-only: no posting, liking, or any other write actions
- TikTok may rate-limit or block scraping from some IPs; tools respond with an empty result + `note` rather than an error
- `get_comments` can return nothing when TikTok hides comments from logged-out browsers
- Transcription requires your own speech-to-text endpoint; nothing is relayed through third parties

## License

MIT
