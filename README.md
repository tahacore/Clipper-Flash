# ⚡ Clipper-Flash

Turn your long YouTube livestreams into short, fun clips — automatically.

You stream for 6 hours. Clipper-Flash watches your channel, reads what you
said (from YouTube's own captions), finds the best moments, and cuts them into
vertical Shorts (with your facecam below your screen) or clean wide videos.
It can even post them to YouTube for you.

**How?** It works *with* your AI coding helper — Claude Code or Codex.
Think of Clipper-Flash as a box of magic scissors, and your AI helper as the
person who decides where to cut. You just say:

> "Clip my latest stream."

...and a few minutes later, finished clips appear in a folder on your computer.

- No extra AI bills (your existing Claude Code or Codex plan does the thinking)
- No server running all day
- Free

---

## What you need (3 things)

| Thing | What it is | Where to get it |
|---|---|---|
| **Python 3.11 or 3.12** | A free program that runs tools like this one | [python.org/downloads](https://www.python.org/downloads/) |
| **FFmpeg** | A free video tool that does the actual cutting | See Step 1 below |
| **uv** | A small installer helper for Python tools | See Step 2 below |

And of course: a YouTube channel with livestreams, plus Claude Code or Codex.

---

## Setup (one time, about 5 minutes)

### Step 1: Install FFmpeg

Open your terminal (on Windows: press Start, type `powershell`, press Enter)
and run the line for your computer:

```bash
# Windows
winget install Gyan.FFmpeg

# Mac (needs Homebrew)
brew install ffmpeg

# Linux (Ubuntu/Debian)
sudo apt install ffmpeg
```

Close and reopen the terminal after this.

### Step 2: Install uv

```bash
# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Mac / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Close and reopen the terminal again.

### Step 3: Install Clipper-Flash

```bash
uv tool install "clipper-flash[vision,web] @ git+https://github.com/tahacore/Clipper-Flash"
```

### Step 4: Check everything works

Type:

```bash
cf doctor
```

You want to see the word **OK** next to every line, like this:

```
OK   ffmpeg          on PATH
OK   ffprobe         on PATH
OK   yt-dlp          python package v...
OK   vision extras   mediapipe + opencv available
OK   state db        ... (0 streams)
```

If something says FAIL, see [Problems?](#problems) at the bottom.

---

## Connect your AI helper (one time)

Your AI helper needs to learn the workflow. Full instructions with pictures of
every step are in **[docs/INSTALL-SKILLS.md](docs/INSTALL-SKILLS.md)**.

Short version:

- **Claude Code:** copy the `skills/clipper-flash` folder into `~/.claude/skills/`
- **Codex:** open the cloned Clipper-Flash folder in Codex (it reads `AGENTS.md` by itself)

---

## Use it (the fun part)

Open Claude Code or Codex and talk like a normal person:

> "Check my channel @yourname and clip anything new."

or

> "Make 5 Shorts from my last stream."

or

> "Turn 1:23:00 to 1:26:30 of <paste video link> into a Short with captions."

### What happens next

1. Your helper looks at your channel and finds streams it hasn't clipped yet.
2. It reads the captions of the whole stream (takes seconds, costs nothing).
3. It picks the best moments and shows you: *"I found these 5 clips — want me
   to make them?"* You say yes (or change things).
4. It downloads **only those minutes** — not the whole 8-hour video.
5. It cuts them into vertical Shorts with captions burned in, your facecam
   tucked under your screen. Or wide videos if you asked for those.
6. Your clips are waiting in the `output` folder. 🎉

### Watch your clips

In any folder where you've made clips, run:

```bash
cf serve
```

Then open http://localhost:8600 in your browser — a little movie gallery of
everything you've made.

---

## Post clips to YouTube automatically (optional)

This uses your own Google account, so nobody else is involved.

1. Go to [console.cloud.google.com](https://console.cloud.google.com/) and make a project.
2. Turn on the **YouTube Data API v3** for it.
3. Create an **OAuth client ID** (type: Desktop app) and download the file.
   Rename it to `client_secret.json`.
4. Install the upload add-on:
   ```bash
   uv tool install "clipper-flash[upload] @ git+https://github.com/tahacore/Clipper-Flash"
   ```
5. Upload a clip:
   ```bash
   cf upload output/myclip.mp4 --title "My best moment" --privacy unlisted
   ```

A browser window opens the first time so you can allow it. After that it
remembers you.

> Heads up: Google sometimes keeps brand-new API uploads locked as *private*
> until they review your project. That's Google's rule, not a bug.

---

## Words we use

| Word | Meaning |
|---|---|
| **Stream / livestream** | The long video while you were live |
| **VOD** | The saved recording of a stream, after it ends |
| **Clip** | A short piece cut out of a VOD |
| **Captions** | The words on YouTube showing what was said |
| **Transcript** | All those words saved in a file we can read |
| **Facecam** | The little video of your face in the corner |
| **Layout** | How a clip looks — e.g. screen on top, facecam below |
| **Agent** | Your AI helper (Claude Code or Codex) |

---

## Problems?

| Problem | Fix |
|---|---|
| `cf` is not recognized | Close and reopen your terminal. Still stuck? Reinstall with Step 3. |
| `ffmpeg NOT FOUND` in `cf doctor` | Install FFmpeg (Step 1), then reopen your terminal. |
| "captions not available" | YouTube hasn't written them yet. Wait ~30–60 minutes and try again. |
| Clips look squished or wrong | Tell your agent which layout you want: `vertical-split`, `face-crop`, or `passthrough`. |
| Agent picked boring clips | Tell it what you like: "pick moments where something funny happened." |
| Upload says private-only | Google locks new API projects. Request an audit, or flip it public yourself on YouTube. |

Still stuck? [Open an issue](https://github.com/tahacore/Clipper-Flash/issues) — we help fast.

---

## For developers

```bash
git clone https://github.com/tahacore/Clipper-Flash && cd Clipper-Flash
uv sync --group dev --extra vision --extra web
uv run pytest -q          # offline unit tests
uv run ruff check src tests
uv run cf doctor
```

Module map and conventions live in [AGENTS.md](AGENTS.md). Roadmap in
[docs/ROADMAP.md](docs/ROADMAP.md).

## Status

Alpha — tested end-to-end against real YouTube data. Expect rough edges; tell
us about them.

## License

MIT — free forever, do what you want.
