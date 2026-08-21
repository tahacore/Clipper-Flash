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
       → clips ready in ./output
```

Why it beats pasting a VOD into a one-shot tool:

- **Captions-first pipeline**: detection runs on free YouTube captions; only the final clips get frame-accurate processing. An 8-hour stream costs seconds of compute, not hours.
- **Sectioned downloads**: never downloads a full 8-hour VOD — only the moments your agent picked (~95% less bandwidth/disk).
- **Coding-stream aware**: the `vertical-split` layout keeps the screen big and pins the facecam strip below — built for dev streams, not just talking heads.
- **Idempotent state**: SQLite remembers what it processed; re-running never duplicates work.

## Install

```bash
# requires: Python 3.11/3.12, FFmpeg on PATH
uv tool install "clipper-flash[vision]"   # vision extra enables facecam detection
cf doctor                                  # verify ffmpeg / yt-dlp / state
```

## Usage with your agent

Install the skill (see [`skills/`](skills/)) into Claude Code or Codex, then just ask:

> "Check my channel and clip anything new from my last stream."

Or drive it manually:

```bash
cf detect --channel UCxxxxxxxxxxxx      # list unprocessed streams
cf transcript <url> -o work/transcript.json
cf pull section <url> --start 1:23:00 --end 1:26:30 -o work/clip.mp4
cf facecam work/clip.mp4
cf render --spec spec.json
```

## Status

Alpha — under active development. See the [roadmap](docs/ROADMAP.md).

## License

MIT
