# Roadmap

## Shipped (v0.1 alpha)

- [x] `cf detect` — RSS channel scan, was-live filter, SQLite dedup, @handle resolution
- [x] `cf transcript` — captions-first transcription (json3/vtt/srv3), rolling-dedup, segments
- [x] `cf pull section/audio` — keyframe-exact section downloads, audio-only fallback
- [x] `cf facecam` — sample-and-vote facecam box (OpenCV YuNet, bundled model)
- [x] `cf render` — vertical-split / face-crop / passthrough + burned ASS captions
- [x] `cf upload` — YouTube posting via user's own OAuth project
- [x] `cf serve` — gallery UI with inline previews
- [x] Agent skill for Claude Code + Codex (`skills/clipper-flash/SKILL.md`)
- [x] End-to-end validated against live YouTube data

## Next

- [ ] **Whisper fallback** — local faster-whisper for channels with captions disabled / non-English streams
- [ ] **Watch mode** — optional `cf watch` daemon (interval polling) for always-on machines
- [ ] **Face-track crop** — per-segment speaker tracking instead of static crop
- [ ] **Podcast layout** — active-speaker switching with blurred pillarbox
- [ ] **Karaoke captions** — word-pop animation styles
- [ ] **Thumbnails** — auto title cards from transcript hooks
- [ ] **Screen-motion tracking** — follow the active window/cursor in vertical-split
- [ ] **Multi-platform posting** — TikTok/Reels via Postiz or platform APIs
- [ ] **Serverless recipe** — GitHub Actions template for zero-server auto clipping
- [ ] **Packaging** — PyPI release, one-click installers

## Non-goals

- Running as a third-party harness over agent subscriptions (policy risk) —
  Clipper-Flash stays a toolkit the *user's own* agent drives.
- Downloading full VODs by default.

