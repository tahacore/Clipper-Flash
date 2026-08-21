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

## Setup — one command

Pick the line for your computer, run it, done. It installs **everything**:
uv, Python, FFmpeg, Clipper-Flash, and the skill for your AI helper.

**Windows** (PowerShell):

```powershell
powershell -c "irm https://raw.githubusercontent.com/tahacore/Clipper-Flash/main/install.ps1 | iex"
```

**Mac / Linux:**

```bash
curl -fsSL https://raw.githubusercontent.com/tahacore/Clipper-Flash/main/install.sh | bash
```

**Already have npm?** (you do if you use Claude Code or Codex CLI)

```bash
npx clipper-flash
```

When it finishes you'll see all-green checkmarks from `cf doctor`. If anything
says FAIL, see [Problems?](#problems) below.

<details>
<summary><strong>Prefer to do it manually?</strong> (click to expand)</summary>

1. Install [FFmpeg](https://ffmpeg.org/download.html) — Windows: `winget install Gyan.FFmpeg`
2. Install [uv](https://docs.astral.sh/uv/) — Windows: `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`
3. `uv tool install "clipper-flash[vision,web] @ git+https://github.com/tahacore/Clipper-Flash"`
4. `cf install-skill` ← copies the skill into Claude Code / Codex for you
5. `cf doctor` to verify

</details>

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
   uv tool install "clipper-flash[upload] @ git+https://github.com/tahacore/Clipper-Flash" --force
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
