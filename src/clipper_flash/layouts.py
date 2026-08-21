"""Layout geometry + FFmpeg filtergraph builders.

Layouts:
- vertical-split : coding-stream template. Screen fills the top region,
                   facecam cropped into a bottom strip. The signature layout.
- face-crop      : classic 9:16 crop centered on the speaker.
- passthrough    : 16:9 long-form, letterboxed if needed.

All builders return (video_filter_chain, Canvas). Input seeking (-ss/-to)
handles trimming, so chains start directly from [0:v].
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Canvas:
    width: int
    height: int


@dataclass
class Box:
    """Pixel-space rectangle in the SOURCE frame."""

    x: int
    y: int
    w: int
    h: int


def default_facecam_box(src_w: int, src_h: int) -> Box:
    """Assumed bottom-right corner cam (~22% width) when detection is unavailable."""
    w = round(src_w * 0.22)
    h = round(w * 9 / 16)
    margin = round(src_w * 0.02)
    return Box(x=src_w - w - margin, y=src_h - h - margin, w=w, h=h)


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def compute_cover_crop(
    src_w: int, src_h: int, region_w: int, region_h: int, avoid: Box | None = None
) -> tuple[int, int, int, int]:
    """Scale source to COVER region, then pick horizontal offset.

    Returns (scaled_w, scaled_h, crop_x, crop_y). If a facecam box would land
    inside the crop window, prefer an offset that excludes it.
    """
    scale = max(region_w / src_w, region_h / src_h)
    sw, sh = round(src_w * scale), round(src_h * scale)

    def cam_center_scaled(box: Box) -> tuple[float, float]:
        return ((box.x + box.w / 2) * scale, (box.y + box.h / 2) * scale)

    candidates = [(sw - region_w) // 2]
    if avoid and sw > region_w:
        ccx, ccy = cam_center_scaled(avoid)
        # try pushing the window away from the cam horizontally
        if ccx > sw / 2:
            candidates = [0, (sw - region_w) // 4, (sw - region_w) // 2]
        else:
            candidates = [sw - region_w, (sw - region_w) * 3 // 4, (sw - region_w) // 2]

        def hits(x: int) -> bool:
            return x <= ccx <= x + region_w and 0 <= ccy <= region_h

        for x in candidates:
            if not hits(x):
                return sw, sh, x, max(0, (sh - region_h) // 2)
    return sw, sh, candidates[0], max(0, (sh - region_h) // 2)


def vertical_split(
    src_w: int,
    src_h: int,
    facecam: Box | None = None,
    strip_h: int = 640,
    out_w: int = 1080,
    out_h: int = 1920,
    **_ignored,
) -> tuple[str, Canvas]:
    """Coding-stream template: screen on top, facecam strip below."""
    strip_h = _clamp(strip_h, 320, out_h // 2)
    screen_h = out_h - strip_h
    cam = facecam or default_facecam_box(src_w, src_h)
    cam = Box(
        x=_clamp(cam.x, 0, src_w - 8),
        y=_clamp(cam.y, 0, src_h - 8),
        w=min(cam.w, src_w - _clamp(cam.x, 0, src_w - 8)),
        h=min(cam.h, src_h - _clamp(cam.y, 0, src_h - 8)),
    )

    sw, sh, crop_x, crop_y = compute_cover_crop(src_w, src_h, out_w, screen_h, avoid=cam)

    screen = (
        f"[0:v]scale=w={sw}:h={sh},crop={out_w}:{screen_h}:{crop_x}:{crop_y},"
        f"setsar=1[screen]"
    )
    camstrip = (
        f"[0:v]crop={cam.w}:{cam.h}:{cam.x}:{cam.y},"
        f"scale=w={out_w}:h={strip_h}:force_original_aspect_ratio=decrease,"
        f"pad={out_w}:{strip_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1[camstrip]"
    )
    merge = "[screen][camstrip]vstack=inputs=2[vpre]"
    return ";".join([screen, camstrip, merge]), Canvas(out_w, out_h)


def face_crop(
    src_w: int,
    src_h: int,
    facecam: Box | None = None,
    out_w: int = 1080,
    out_h: int = 1920,
    **_ignored,
) -> tuple[str, Canvas]:
    """Classic vertical crop centered on the speaker."""
    win_w = min(src_w, round(src_h * out_w / out_h))
    cam = facecam or default_facecam_box(src_w, src_h)
    cx = cam.x + cam.w / 2
    x = _clamp(round(cx - win_w / 2), 0, src_w - win_w)
    chain = (
        f"[0:v]crop={win_w}:{src_h}:{x}:0,"
        f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{out_h},setsar=1[vpre]"
    )
    return chain, Canvas(out_w, out_h)


def passthrough(
    src_w: int,
    src_h: int,
    facecam: Box | None = None,
    out_w: int = 1920,
    out_h: int = 1080,
    **_ignored,
) -> tuple[str, Canvas]:
    """Long-form 16:9 with letterbox padding when needed."""
    chain = (
        f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
        f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1[vpre]"
    )
    return chain, Canvas(out_w, out_h)


LAYOUTS = {
    "vertical-split": vertical_split,
    "face-crop": face_crop,
    "passthrough": passthrough,
}


def aspect_hint(width: int, height: int) -> str:
    """Human-readable orientation tag used in output naming."""
    r = width / height if height else 1.0
    if math.isclose(r, 16 / 9, rel_tol=0.05):
        return "wide"
    if r < 0.8:
        return "shorts"
    return "square"
