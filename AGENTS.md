# AGENTS.md — Clipper-Flash

Agent-native clipping toolkit: deterministic `cf` CLI + agent judgment.
User-facing workflow lives in [`skills/clipper-flash/SKILL.md`](skills/clipper-flash/SKILL.md) —
read it before driving the toolkit end-to-end.

## What this repo is

`src/clipper_flash/` modules, one concern each:

| module | responsibility |
|---|---|
| `cli.py` | typer command surface (`cf ...`), exit codes: 0 ok / 1 error / 2 retry-later |
| `state.py` | SQLite idempotency (streams/clips), default DB `~/.clipper-flash/state.db` |
| `youtube.py` | RSS feeds, yt-dlp metadata probes, channel-id resolution |
| `detect.py` | channel scan → unprocessed former-livestreams |
| `transcript.py` | caption track pick/download, json3+vtt parsing, cleaning, segments |
| `pull.py` | exact section downloads (`--download-sections` + keyframe-exact) and audio-only |
| `facecam.py` | sample-and-vote facecam box detection (OpenCV YuNet) |
| `scenes.py` | screen+cam vs cam-only classification + shot cuts (`cf scenes`) |
| `layouts.py` | filtergraph geometry: stacked / fullframe / vertical-split / passthrough |
| `subtitles.py` | ASS caption generation from transcript words |
| `render.py` | spec-driven ffmpeg rendering |

## Dev commands

```bash
uv sync --group dev --extra vision   # install with dev tools + face detection
uv run pytest -q                     # tests (offline; no network in unit tests)
uv run ruff check src tests          # lint
uv run cf doctor                     # runtime dependency check
```

## Conventions

- Keep network I/O out of pure logic; inject fetchers/probes for testability.
- Every CLI command supports `--json` for machine-readable output.
- Never commit user media, transcripts, or the state DB (`work/`, `output/`, `*.db`).
- Python >=3.11,<3.13 (OpenCV YuNet wheel support).
