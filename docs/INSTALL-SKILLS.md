# Connecting your agent

Clipper-Flash ships as a **skill**: a workflow document your coding agent reads
so it drives the `cf` toolkit like an experienced editor would. Install takes
one minute.

## Claude Code (CLI or desktop)

**Personal (all projects):**

```bash
# copy the skill folder into your personal skills directory
mkdir -p ~/.claude/skills
cp -r /path/to/Clipper-Flash/skills/clipper-flash ~/.claude/skills/
```

**Project-only:** copy `skills/clipper-flash/` into `<project>/.claude/skills/`.

Verify: start Claude Code, type `/skills` — `clipper-flash` should be listed.
Then just ask:

> "Check my channel @yourhandle and clip anything new."

## Codex (desktop or CLI)

Codex reads `AGENTS.md` files. Two options:

1. **Per-repo:** clone Clipper-Flash anywhere; open that folder in Codex and it
   picks up `AGENTS.md` → which points at the full skill. Ask:
   > "Read skills/clipper-flash/SKILL.md and clip my latest stream."
2. **Global:** append the skill to your global instructions file so every
   session knows the workflow:
   - Linux/macOS: `~/.codex/AGENTS.md`
   - Windows: `%USERPROFILE%\.codex\AGENTS.md`

   ```markdown
   ## Clipper-Flash
   When asked to clip/repurpose YouTube livestreams, follow the workflow in
   <path-to>/Clipper-Flash/skills/clipper-flash/SKILL.md exactly.
   ```

## One-time setup checklist (both agents)

```bash
cf doctor    # everything should print OK
```

- FFmpeg installed and on PATH (`winget install Gyan.FFmpeg` / brew / apt)
- Python 3.11–3.12 + `uv tool install "clipper-flash[vision,web]"`
- Optional: `[upload]` extra + Google OAuth client secret (README → Auto-upload)

## What to expect on first run

1. Agent runs `cf detect` — your recent livestreams appear with durations.
2. It fetches captions (seconds) and reads the whole transcript.
3. It proposes 3–8 clips: title + timestamp range + why. **You approve.**
4. It downloads only those sections, detects the facecam once, renders 1080×1920
   Shorts with burned captions (or 16:9 if you asked for long-form).
5. Clips land in `output/<video_id>/` — preview them with `cf serve`.
