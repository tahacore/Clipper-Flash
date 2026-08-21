---
name: clipper-flash
description: Turn YouTube livestreams into Shorts & highlight clips using the deterministic cf toolkit. Use when the user asks to clip, find highlights in, or repurpose their livestream/VOD content, or to check their channel for new streams to process.
---

# Clipper-Flash

You are driving a deterministic video toolkit (`cf`). Your job is the *judgment*
work — picking moments, writing titles — while `cf` handles downloads, caption
parsing, facecam detection, and rendering. Never download a full VOD; never
guess timestamps without reading the transcript.

## 0. Preflight

Run `cf doctor` first. If ffmpeg/ffprobe are missing, tell the user to install
FFmpeg and stop. If vision extras are missing you may continue, but
`vertical-split` will fall back to an assumed bottom-right facecam box.

## 1. Find work

```
cf detect <channel>          # channel id (UC...), @handle, or any channel/video URL
cf streams --json            # everything tracked + pipeline status
```

Process streams whose status is `new` or `captions_pending` (oldest first).
Status meanings:

| status | meaning | action |
|---|---|---|
| new | detected, not transcribed | continue to step 2 |
| captions_pending | captions not ready yet | skip, retry later (>30 min after publish) |
| transcribed | transcript saved | continue to step 3 |
| clipped | done | skip |
| skipped | not a livestream | skip |
| failed | a stage errored | investigate `error`, then redo failed stage |

## 2. Transcribe (captions-first)

```
cf transcript <url> -o work/<video_id>.transcript.json --json
```

- Exit code **0**: proceed. Exit code **2** means captions aren't available yet
  (YouTube generates them minutes-to-hours after publish): mark mentally as
  retry-later, do NOT treat as failure.
- Read `segments` from the JSON. Each has `{start, end, text}` in seconds.
  For an 8h stream expect ~5k segments (~100k tokens) — read all of them;
  long context is exactly what you're good at.

## 3. Pick highlights (your main job)

Select the best **3–8 self-contained moments**, each **30–90 seconds**
(Shorts sweet spot: 45–70s). Score each candidate segment window on:

1. **Hook** (0–10): does the first 3 seconds grab? A strong claim, question,
   number, or emotional beat. Weak openers kill clips.
2. **Self-containedness** (0–10): understandable without prior context?
   No dangling references ("as I said before", "that chat message").
3. **Payoff** (0–10): does it land an insight, joke, story resolution, or
   practical takeaway by the end?
4. **Flow** (0–10): no mid-sentence starts/stops, no dead air >2s inside.

Keep only windows scoring ≥7 average. Boundary rules:

- Snap start/end to sentence boundaries using segment times.
- Extend start up to 3s earlier if it captures the lead-in of the key sentence.
- Trim trailing silence using the last word's `end`.
- Prefer moments spread across the stream over clustered ones.
- For coding streams, prefer moments where something on screen matters
  (bugfix reveal, demo, result) — they render well in vertical-split.

For each kept moment record: `start`, `end` (absolute stream seconds),
a spoken-language `title` (≤60 chars, no clickbait clichés), and a one-line
`reason`.

Present your picks to the user (title + timestamp range + reason) and get a
confirm unless they pre-approved auto mode.

## 4. Download only the chosen sections

```
cf pull section <url> <start> <end> -o work/<video_id>__<start>-<end>.mp4
```

(one call per clip; cuts are keyframe-exact, so file t=0 == requested start)

## 5. Facecam (for vertical layouts)

```
cf facecam work/<video_id>__<start>-<end>.mp4 --json
```

Use the first pulled section. Pass the returned box into every spec clip of
that stream. If it fails (exit 2), omit `facecam` — vertical-split assumes a
bottom-right cam.

## 6. Write the spec & render

`work/<video_id>.spec.json`:

```json
{
  "clips": [
    {
      "input":  "work/<video_id>__4980-5040.mp4",
      "out":    "output/<video_id>/01-<slug>.mp4",
      "title":  "<your title>",
      "layout": "vertical-split",
      "start": 0.0, "end": 60.0,
      "captions": true,
      "transcript": "work/<video_id>.transcript.json",
      "abs_start": 4980.0,
      "facecam": {"x": 1490, "y": 793, "w": 422, "h": 237}
    }
  ]
}
```

Layouts: `vertical-split` (screen top + facecam strip below — default for
coding/dev streams), `face-crop` (talking-head), `passthrough` (16:9 long-form;
use `start`/`end` relative to input, captions still supported).

```
cf render work/<video_id>.spec.json --video-id <video_id> --json
```

## 7. Verify (never skip)

For each output file run ffprobe: duration within ±1s of requested, both
audio+video streams present, size > 500KB. Watch for: zero-byte files,
missing audio (no `-map 0:a?` output), stretched aspect ratio. Re-render any
failures with adjusted bounds. Then show the user the list with paths.

## 8. Optional: post to YouTube

If the user asks to publish and `cf upload` is configured (see README
"Auto-upload"), upload each clip with its title plus a standard description
and `#shorts` for vertical clips. Otherwise leave files in `output/` and say so.

## Guardrails

- Never process a stream the user didn't claim (detect defaults to their own
  channels; refuse third-party VODs unless the user confirms they have rights).
- Don't fabricate timestamps: every number must come from transcript/pull data.
- One stream at a time; finish or clearly park it before starting another.
