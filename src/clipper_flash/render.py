"""Render engine: turn clip specs into finished MP4s with FFmpeg.

Spec file schema (what the agent writes after picking moments):

{
  "clips": [
    {
      "input": "work/<video_id>__<start>-<end>.mp4",
      "out": "output/<video_id>/01-title.mp4",
      "title": "optional title (metadata only)",
      "layout": "stacked" | "fullframe" | "vertical-split" | "face-crop" | "passthrough",
      "start": 0.0,                  # seconds, relative to input file
      "end": 60.0,
      "captions": "hype",            # true | false | style name
      "transcript": "work/t.json",
      "abs_start": 4980.0,           # absolute stream time of input's t=0
      "facecam": {"x":..,"y":..,"w":..,"h":..},
      "cam_h": 960,                  # stacked only
      "screen_h": 608,               # stacked only
      "strip_height": 640,           # vertical-split only
      "caption_margin_v": 700,
      "segments": [                  # optional; tiles start..end
        {"start": 0.0, "end": 12.0, "layout": "stacked", "facecam": {...}},
        {"start": 12.0, "end": 40.0, "layout": "fullframe", "facecam": {...}}
      ]
    }
  ]
}
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from clipper_flash.layouts import (
    LAYOUTS,
    SHORTS_LAYOUTS,
    STACKED_CAM_H,
    STACKED_SCREEN_H,
    Box,
    stacked_caption_margin,
)
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
    poster: str | None = None


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


def _box(fc: dict | None) -> Box | None:
    if not fc:
        return None
    return Box(int(fc["x"]), int(fc["y"]), int(fc["w"]), int(fc["h"]))


def _layout_kwargs(clip: dict, layout_name: str) -> dict:
    kwargs: dict = {}
    if layout_name == "vertical-split":
        kwargs["strip_h"] = int(clip.get("strip_height", 640))
    if layout_name == "stacked":
        kwargs["cam_h"] = int(clip.get("cam_h", STACKED_CAM_H))
        kwargs["screen_h"] = int(clip.get("screen_h", STACKED_SCREEN_H))
    return kwargs


def default_caption_margin(layout_name: str, clip: dict, canvas_h: int) -> int:
    """Place captions in the Shorts safe zone for the chosen layout."""
    if layout_name == "vertical-split":
        return int(clip.get("strip_height", 640)) + 24
    if layout_name == "stacked":
        return stacked_caption_margin(
            int(clip.get("cam_h", STACKED_CAM_H)),
            int(clip.get("screen_h", STACKED_SCREEN_H)),
            canvas_h,
        )
    if layout_name in ("face-crop", "fullframe"):
        return int(canvas_h * 0.38)  # chest, above YouTube chrome
    return 60


def normalize_segments(clip: dict, start: float, end: float) -> list[dict]:
    """Return contiguous file-relative segments covering [start, end]."""
    raw = clip.get("segments")
    default_layout = clip.get("layout", "passthrough")
    if not raw:
        return [{
            "start": start,
            "end": end,
            "layout": default_layout,
            "facecam": clip.get("facecam"),
        }]
    segs: list[dict] = []
    cursor = start
    for i, s in enumerate(raw):
        a = float(s.get("start", cursor))
        b = float(s.get("end", end))
        if b <= a + 0.05:
            raise RenderError(f"segment {i} too short ({a:.2f}-{b:.2f})")
        if abs(a - cursor) > 0.08:
            raise RenderError(
                f"segments must tile the clip contiguously "
                f"(gap before segment {i}: expected {cursor:.3f}, got {a:.3f})"
            )
        layout = s.get("layout", default_layout)
        if layout not in LAYOUTS:
            raise RenderError(f"unknown layout {layout!r}; choose from {sorted(LAYOUTS)}")
        segs.append({
            "start": a,
            "end": b,
            "layout": layout,
            "facecam": s.get("facecam", clip.get("facecam")),
        })
        cursor = b
    if abs(cursor - end) > 0.08:
        raise RenderError(
            f"segments must cover the clip end (last {cursor:.3f}, clip end {end:.3f})"
        )
    return segs


def render_clip(clip: dict, workdir: str | Path = "work") -> RenderResult:
    src = Path(clip["input"])
    if not src.exists():
        raise RenderError(f"input missing: {src}")
    info = probe(src)

    start = max(float(clip.get("start", 0.0)), 0.0)
    end = min(float(clip.get("end", info["duration"])), info["duration"])
    if end - start < 1.0:
        raise RenderError(f"clip too short ({end - start:.1f}s)")

    segs = normalize_segments(clip, start, end)
    layout_name = segs[0]["layout"]
    if layout_name not in LAYOUTS:
        raise RenderError(f"unknown layout {layout_name!r}; choose from {sorted(LAYOUTS)}")

    chains: list[str] = []
    canvas = None
    for i, seg in enumerate(segs):
        name = seg["layout"]
        kwargs = _layout_kwargs(clip, name)
        kwargs["in_label"] = f"{i}:v"
        kwargs["out_label"] = f"v{i}"
        chain, canvas = LAYOUTS[name](
            info["width"], info["height"], facecam=_box(seg.get("facecam")), **kwargs
        )
        chains.append(chain)

    assert canvas is not None
    n = len(segs)
    if n == 1:
        # Keep historical labels so existing tests can grep [vpre]/[vout].
        video_body = chains[0].replace("[v0]", "[vpre]")
        vpre = "vpre"
    else:
        concat_v = "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vpre]"
        video_body = ";".join([*chains, concat_v])
        vpre = "vpre"

    cap_setting = clip.get("captions", False)
    if isinstance(cap_setting, str):
        cap_style: str | None = cap_setting
    elif cap_setting:
        cap_style = "hype" if layout_name in SHORTS_LAYOUTS else "clean"
    else:
        cap_style = None
    cap_margin = clip.get("caption_margin_v")
    if cap_margin is None:
        cap_margin = default_caption_margin(layout_name, clip, canvas.height)
    emphasis = [str(e) for e in clip.get("emphasis", [])]
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
            margin_v_override=cap_margin,
            emphasis=emphasis,
        )

    out_path = Path(clip["out"])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # One sequential chain consumes [vpre]: fades -> (captions) -> pixfmt.
    post: list[str] = []
    polish = clip.get("polish", True)
    dur = end - start
    if polish:
        post.append(f"fade=t=in:st=0:d=0.04,fade=t=out:st={max(dur - 0.25, 0):.3f}:d=0.25")
    if ass_path:
        post.append(f"{_ass_filter_arg(ass_path)}")
    post.append("format=yuv420p")
    video_chain = f"{video_body};[{vpre}]" + ",".join(post) + "[vout]"

    cmd: list[str] = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for seg in segs:
        cmd += ["-ss", f"{seg['start']:.3f}", "-to", f"{seg['end']:.3f}", "-i", str(src)]
    cmd += ["-filter_complex", video_chain, "-map", "[vout]"]

    if n == 1:
        cmd += ["-map", "0:a?"]
        if polish:
            cmd += [
                "-af",
                f"loudnorm=I=-14:TP=-1.5:LRA=11,"
                f"afade=t=in:st=0:d=0.04,afade=t=out:st={max(dur - 0.35, 0):.3f}:d=0.35",
            ]
    else:
        a_concat = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1"
        if polish:
            a_concat += (
                f",loudnorm=I=-14:TP=-1.5:LRA=11,"
                f"afade=t=in:st=0:d=0.04,afade=t=out:st={max(dur - 0.35, 0):.3f}:d=0.35"
            )
        video_chain = video_chain + f";{a_concat}[aout]"
        # rebuild cmd filter_complex with audio concat on the same graph
        fc_idx = cmd.index("-filter_complex")
        cmd[fc_idx + 1] = video_chain
        cmd += ["-map", "[aout]"]

    cmd += [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RenderError(f"ffmpeg failed:\n{proc.stderr[-2000:]}")

    poster = _extract_poster(out_path, dur)

    return RenderResult(
        out=str(out_path),
        layout=layout_name if n == 1 else "segments",
        width=canvas.width,
        height=canvas.height,
        duration_sec=round(end - start, 2),
        captions=bool(ass_path),
        poster=poster,
    )


def _extract_poster(out_path: Path, duration: float) -> str | None:
    """Grab a frame at ~8% in as the gallery poster (hook, not a random blink)."""
    try:
        poster = out_path.with_name(out_path.stem + ".poster.jpg")
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{max(duration * 0.08, 0.4):.3f}", "-i", str(out_path),
            "-frames:v", "1", "-q:v", "3", str(poster),
        ]
        subprocess.run(cmd, capture_output=True, text=True)
        if poster.exists() and poster.stat().st_size > 0:
            return str(poster)
    except Exception:  # noqa: BLE001 - posters are best-effort
        pass
    return None


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
    if errors:
        # Surface partial failure so agents don't treat the spec as fully done.
        raise RenderError(f"some clips failed: {errors}; succeeded={len(results)}")
    return results
