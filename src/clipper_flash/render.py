"""Render engine: turn clip specs into finished MP4s with FFmpeg.

Spec file schema (what the agent writes after picking moments):

{
  "clips": [
    {
      "input": "work/<video_id>__<start>-<end>.mp4",
      "out": "output/<video_id>/01-title.mp4",
      "title": "optional title (metadata only)",
      "layout": "vertical-split" | "face-crop" | "passthrough",
      "start": 0.0,                  # seconds, relative to input file
      "end": 60.0,
      "captions": true,              # true | false | style name ("bold","clean")
      "transcript": "work/t.json",   # transcript json (absolute-time words)
      "abs_start": 4980.0,           # absolute stream time of input's t=0
      "facecam": {"x":..,"y":..,"w":..,"h":..},  # optional px box in source
      "strip_height": 640,           # vertical-split only
      "caption_margin_v": 700        # optional; vertical-split auto-places
                                     # captions above the strip by default
    }
  ]
}
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from clipper_flash.layouts import LAYOUTS, Box
from clipper_flash.subtitles import make_captions_for_clip


class RenderError(RuntimeError):
    pass


@dataclass
class RenderResult:
    out: str
    layout: str
    width: int
    height: int
    duration_sec: float
    captions: bool


def probe(path: str | Path) -> dict:
    """ffprobe a media file: width/height/duration/fps."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate:format=duration",
        "-of", "json", str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RenderError(f"ffprobe failed for {path}: {proc.stderr[-500:]}")
    data = json.loads(proc.stdout or "{}")
    try:
        stream = data["streams"][0]
        num, _, den = (stream.get("r_frame_rate") or "30/1").partition("/")
        fps = float(num) / float(den or 1)
        return {
            "width": int(stream["width"]),
            "height": int(stream["height"]),
            "duration": float(data["format"]["duration"]),
            "fps": fps,
        }
    except (KeyError, IndexError, ValueError) as exc:
        raise RenderError(f"unexpected ffprobe output for {path}") from exc


def _ass_filter_arg(ass_path: Path) -> str:
    """Escape an ass path for use inside a filtergraph (windows-safe).

    The drive-letter colon must be escaped or ffmpeg splits it as an arg
    separator; forward slashes keep backslash escapes out of the picture.
    """
    p = ass_path.resolve().as_posix().replace(":", "\\:")
    return f"ass='{p}'"


def render_clip(clip: dict, workdir: str | Path = "work") -> RenderResult:
    src = Path(clip["input"])
    if not src.exists():
        raise RenderError(f"input missing: {src}")
    info = probe(src)

    start = max(float(clip.get("start", 0.0)), 0.0)
    end = min(float(clip.get("end", info["duration"])), info["duration"])
    if end - start < 1.0:
        raise RenderError(f"clip too short ({end - start:.1f}s)")

    layout_name = clip.get("layout", "passthrough")
    if layout_name not in LAYOUTS:
        raise RenderError(f"unknown layout {layout_name!r}; choose from {sorted(LAYOUTS)}")

    facecam = None
    if clip.get("facecam"):
        fc = clip["facecam"]
        facecam = Box(int(fc["x"]), int(fc["y"]), int(fc["w"]), int(fc["h"]))

    kwargs: dict = {}
    if layout_name == "vertical-split":
        kwargs["strip_h"] = int(clip.get("strip_height", 640))
    chain, canvas = LAYOUTS[layout_name](
        info["width"], info["height"], facecam=facecam, **kwargs
    )

    cap_setting = clip.get("captions", False)
    cap_style = cap_setting if isinstance(cap_setting, str) else ("bold" if cap_setting else None)
    cap_margin = clip.get("caption_margin_v")
    if cap_margin is None and layout_name == "vertical-split":
        # Default: sit just ABOVE the facecam strip instead of covering it.
        cap_margin = int(clip.get("strip_height", 640)) + 24
    ass_path: Path | None = None
    if cap_style and clip.get("transcript"):
        t_path = Path(clip["transcript"])
        words = json.loads(t_path.read_text(encoding="utf-8")).get("words", [])
        abs_start = float(clip.get("abs_start", 0.0))
        out_path = Path(clip["out"])
        ass_path = make_captions_for_clip(
            words,
            abs_start,
            start,
            end,
            out_path=out_path.with_suffix(".ass"),
            width=canvas.width,
            height=canvas.height,
            style=cap_style,
            margin_v_override=int(cap_margin) if cap_margin is not None else None,
        )

    out_path = Path(clip["out"])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    video_chain = chain
    polish = clip.get("polish", True)
    dur = end - start
    if polish:
        video_chain += (
            f";[vpre]fade=t=in:st=0:d=0.15,fade=t=out:st={max(dur - 0.25, 0):.3f}:d=0.25"
        )
    if ass_path:
        video_chain += f";[vpre]{_ass_filter_arg(ass_path)},format=yuv420p[vout]"
    else:
        video_chain += ";[vpre]format=yuv420p[vout]"

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(src),
        "-filter_complex", video_chain,
        "-map", "[vout]", "-map", "0:a?",
    ]
    if polish:
        # -14 LUFS matches YouTube/Shorts loudness target; fades avoid abrupt edges
        cmd += [
            "-af",
            f"loudnorm=I=-14:TP=-1.5:LRA=11,"
            f"afade=t=in:st=0:d=0.15,afade=t=out:st={max(dur - 0.35, 0):.3f}:d=0.35",
        ]
    cmd += [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RenderError(f"ffmpeg failed:\n{proc.stderr[-2000:]}")

    return RenderResult(
        out=str(out_path),
        layout=layout_name,
        width=canvas.width,
        height=canvas.height,
        duration_sec=round(end - start, 2),
        captions=bool(ass_path),
    )


def render_spec_file(spec_path: str | Path) -> list[RenderResult]:
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    return render_spec_from_dict(spec)


def render_spec_from_dict(spec: dict) -> list[RenderResult]:
    clips = spec.get("clips")
    if not clips:
        raise RenderError("spec has no clips")
    results: list[RenderResult] = []
    errors: list[dict] = []
    for i, clip in enumerate(clips):
        try:
            results.append(render_clip(clip))
        except RenderError as exc:
            errors.append({"index": i, "title": clip.get("title", ""), "error": str(exc)})
    if errors and not results:
        raise RenderError(f"all clips failed: {errors}")
    return results
