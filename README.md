# TikTok MCP Server

[![M8ven Score](https://m8ven.ai/badge/mcp/nuelcyoung-tiktok-mcp-server-izb1xs)](https://m8ven.ai/mcp/nuelcyoung-tiktok-mcp-server-izb1xs?s=readme)

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
        "TRANSCRIBE_API_URL": "https://api.groq.com/openai/v1/audio/transcriptions",
        "TRANSCRIBE_API_KEY": "your-key",
        "TRANSCRIBE_MODEL": "your-model"
      }
    }
  }
}
```

Things worth knowing before the first call:

- The `env` block exists only for `transcribe_video`. Write `"env": {}` if you want the other five tools and nothing else. `TRANSCRIBE_API_URL` is used exactly as written, so give the provider's full speech-to-text endpoint: an OpenAI-compatible multipart `POST` (the `/audio/transcriptions` route) backed by a speech-to-text model such as `whisper-large-v3`.
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
- When TikTok blocks or hides data, tools return an empty list plus a `note` instead of failing, and requests are paced so repeat calls wait rather than pile on
- Each browser call takes several seconds; `transcribe_video` can take up to a minute. Counts like views/likes are TikTok's display strings (e.g. `1.2M`)

## Configuration

Your MCP client injects configuration as environment variables. The server never reads a `.env` file of its own.

| Variable | Required | Description |
|----------|----------|-------------|
| `TRANSCRIBE_API_URL` | For transcription | Full speech-to-text endpoint, used verbatim (`https://api.groq.com/openai/v1/audio/transcriptions`, `https://api.openai.com/v1/audio/transcriptions`, `http://localhost:8000/v1/audio/transcriptions`) |
| `TRANSCRIBE_API_KEY` | For transcription | API key for that endpoint (omit for keyless local servers) |
| `TRANSCRIBE_MODEL` | No | Model name (default `whisper-large-v3`; use `whisper-1` for OpenAI) |
| `FFMPEG_PATH` | No | Path to an ffmpeg binary (default: `ffmpeg` on PATH, else the bundled one) |
| `TIKTOK_MCP_HEADLESS` | No | `false` shows the browser while debugging (default `true`) |
| `TIKTOK_MCP_LOG_LEVEL` | No | `DEBUG`, `INFO` (default), `WARNING`, `ERROR` |

Request pacing (defaults follow a person browsing; raise them if you see blocks, lower them if calls feel slow):

| Variable | Default | Description |
|----------|---------|-------------|
| `TIKTOK_MCP_MIN_INTERVAL_S` | `4` | Minimum seconds between TikTok requests |
| `TIKTOK_MCP_REQUESTS_PER_WINDOW` | `24` | Requests allowed per window |
| `TIKTOK_MCP_WINDOW_S` | `300` | Length of that window |
| `TIKTOK_MCP_COOLDOWN_S` | `90` | First cooldown after a block; doubles on each further block |
| `TIKTOK_MCP_COOLDOWN_MAX_S` | `900` | Ceiling for that doubling |
| `TIKTOK_MCP_SETTLE_MS` | `2500` | How long a page is given to finish rendering |
| `TIKTOK_MCP_CACHE_TTL_S` | `300` | How long a read is reused instead of re-requested (`0` disables) |

Browser identity and footprint:

| Variable | Default | Description |
|----------|---------|-------------|
| `TIKTOK_MCP_PERSIST_PROFILE` | `true` | Reuse one browser profile so TikTok's cookies survive restarts |
| `TIKTOK_MCP_PROFILE_DIR` | OS cache dir | Where that profile lives (`%LOCALAPPDATA%\tiktok-mcp\browser-profile`) |
| `TIKTOK_MCP_CHANNEL` | auto | Force `chrome`, `msedge`, or `chromium`; auto prefers an installed Chrome/Edge over bundled Chromium |
| `TIKTOK_MCP_BLOCK_TELEMETRY` | `true` | Drop TikTok's ad and telemetry calls |

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
        "TRANSCRIBE_API_URL": "https://api.groq.com/openai/v1/audio/transcriptions",
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
    "TRANSCRIBE_API_URL": "https://api.groq.com/openai/v1/audio/transcriptions",
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
TRANSCRIBE_API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
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

### Not getting rate-limited

TikTok blocks scraping clients that look like bots and that hammer the site. The server is built to avoid both, without any hidden tricks:

- **Paced, never bursty.** Every TikTok request — the warm-up visit, each scrape, each media download — takes a slot from one server-wide gate: a minimum gap between requests plus a sliding-window budget. Tools called in parallel queue up instead of landing at once.
- **One identity, not a new one per call.** A persistent browser profile keeps TikTok's cookies (`ttwid`, `msToken`) across calls and restarts, the homepage is warmed up once per session rather than before every page, and the headless fingerprint (`HeadlessChrome`, `navigator.webdriver`) is replaced with an installed Chrome's real version.
- **Repeats are free.** Identical reads are served from a short-lived cache, and simultaneous identical requests share one page load, so a retry or a re-plan costs TikTok nothing.
- **Blocks are respected.** A rate-limit response (HTTP 429/403, or TikTok's error copy) starts a cooldown that every later call waits out, doubling on each repeat — the opposite of retrying into a longer ban. The tool tells you how long to wait instead of failing silently.

Defaults are deliberately conservative (a request every 4 s, 24 per 5 minutes). Tune them with the pacing variables above.

## Architecture

```
src/tiktokmcp/
├── __main__.py      # python -m tiktokmcp
├── server.py        # create_server() factory, instructions, CLI (--transport/--host/--port)
├── app.py           # lifespan + AppContext (throttle, cache, browser, scraper, transcriber)
├── config.py        # Settings.from_env()
├── models.py        # Pydantic result models -> outputSchema / structuredContent
├── errors.py        # domain errors -> ToolError translation
├── validation.py    # username / video-reference normalization
├── throttle.py      # request pacing, sliding window, block cooldowns
├── cache.py         # TTL cache with single-flight de-duplication
├── browser.py       # BrowserManager: persistent Playwright profile, owned by the lifespan
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
- TikTok still rate-limits some IPs and some accounts. When that happens tools return an empty result plus a `note` saying how long to wait, and the server stops requesting for that long instead of retrying
- `get_comments` can return nothing when TikTok hides comments from logged-out browsers
- Transcription requires your own speech-to-text endpoint; nothing is relayed through third parties

## License

MIT
