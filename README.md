# ⚡ Clipper-Flash

**Agent-native clipping toolkit** — turn YouTube livestreams into Shorts & highlight clips using your coding agent (Claude Code / Codex) as the brain.

No API keys. No subscriptions. No 24/7 server. If you already have a Claude Code or Codex plan, you already have everything Clipper-Flash needs.

## How it works

You talk to your agent. Your agent drives the deterministic `cf` toolkit:

```
you:   "clip my latest stream"
agent: cf detect      → finds unprocessed VODs via RSS (no API key)
       cf transcript  → fetches YouTube captions (~seconds, free)
       <agent reads transcript, picks the best moments, writes titles>
       cf pull        → downloads ONLY the chosen sections in full quality
       cf facecam     → locates the facecam region once per stream
       cf render      → FFmpeg layouts: vertical split / crop / captions
       cf upload      → optional: posts to YouTube
       → clips ready in ./output
```

Why it beats pasting a VOD into a one-shot tool:

- **Captions-first pipeline**: detection runs on free YouTube captions; only the final clips get frame-accurate processing. An 8-hour stream costs seconds of compute, not hours.
- **Sectioned downloads**: never downloads a full 8-hour VOD — only the moments your agent picked (~95% less bandwidth/disk).
- **Coding-stream aware**: the `vertical-split` layout keeps the screen big and pins the facecam strip below — built for dev streams, not just talking heads.
- **Idempotent state**: SQLite remembers what it processed; re-running never duplicates work.
- **Reviewable**: every pick is shown with timestamps + reasons before rendering.

## Install

Requirements: Python 3.11 or 3.12, [FFmpeg](https://ffmpeg.org/download.html) on PATH, and [uv](https://docs.astral.sh/uv/).

```bash
uv tool install "clipper-flash[vision,web]"   # face detection + gallery UI
cf doctor                                     # verify everything
```

Then connect your agent — see **[docs/INSTALL-SKILLS.md](docs/INSTALL-SKILLS.md)** for Claude Code and Codex (desktop or CLI).

## Usage

Ask your agent anything like:

> "Check my channel and clip anything new from my last stream."
> "Turn 1:23:00–1:26:30 of <url> into a Short with captions."

Or drive it manually:

```bash
cf detect @yourhandle                    # list unprocessed streams
cf streams --json                        # pipeline status
cf transcript <url> -o work/t.json       # captions → clean transcript
cf pull section <url> 1:23:00 1:26:30 -o work/clip.mp4
cf facecam work/clip.mp4 --json
cf render work/spec.json --video-id <id>
cf serve                                 # gallery at http://localhost:8600
```

Exit codes: `0` ok · `1` error · `2` retry-later (e.g. captions still processing). Every command supports `--json`.

## Auto-upload (optional)

Clips can be posted to YouTube automatically using *your own* Google OAuth project:

1. [Google Cloud Console](https://console.cloud.google.com/) → new project → enable **YouTube Data API v3**.
2. APIs & Services → Credentials → **Create credentials → OAuth client ID → Desktop app** → download JSON as `client_secret.json`.
3. Install the extra: `uv tool install "clipper-flash[upload]"`.
4. Upload:
   ```bash
   cf upload output/myclip.mp4 --title "My clip" --privacy unlisted --tags "#shorts"
   ```

First run opens a browser for consent; the token is cached in `~/.clipper-flash/oauth_token.json`.

> **Note:** until Google audits your API project, YouTube may lock API uploads to *private*. That's platform policy, not a bug — request an audit or flip visibility manually.

## Development

```bash
git clone https://github.com/tahacore/Clipper-Flash && cd Clipper-Flash
uv sync --group dev --extra vision --extra web
uv run pytest -q          # offline unit tests
uv run ruff check src tests
uv run cf doctor
```

See [AGENTS.md](AGENTS.md) for the module map and conventions.

## Status

Alpha — core pipeline is end-to-end tested against real YouTube data. Roadmap: [docs/ROADMAP.md](docs/ROADMAP.md).

## License

MIT
