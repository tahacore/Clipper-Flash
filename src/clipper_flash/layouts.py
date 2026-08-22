"""Layout geometry + FFmpeg filtergraph builders.

Layouts:
- stacked        : coding-stream template (default for Shorts with a
                   facecam overlay). Face COVER-fills a top card over a
                   blurred backdrop; the ENTIRE 16:9 screen is fitted
                   below. Captions burn onto the screen card.
- fullframe      : camera-only / podcast. One 9:16 cover crop on the
                   active speaker.
- face-crop      : alias of fullframe (legacy name).
- vertical-split : legacy coding template (screen cover-cropped on top,
                   facecam strip below). Kept for compatibility.
- passthrough    : 16:9 long-form, letterboxed if needed.

Builders return (video_filter_chain, Canvas). Input seeking (-ss/-to)
handles trimming. `in_label` / `out_label` let a multi-segment render
feed [N:v] and collect [v0]/[v1]/...
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Packed against the reference Shorts: big cam, 16:9 screen, thin
# Shorts-chrome strip at the bottom — not a 600px void.
STACKED_MARGIN = 24
STACKED_GAP = 20
STACKED_BOTTOM = 220
STACKED_SCREEN_H = 580  # 16:9 of (1080 - 2*24)
STACKED_CAM_H = 1076  # 1920 - margin - gap - screen - bottom
# Forehead-cam / giant overlay: COVER into the tall card becomes a
# macro of glasses. Cap the upscale and sit the overlay on the blur.
STACKED_CLOSEUP_MIN_H = 0.42  # fraction of source height
STACKED_CLOSEUP_MAX_SCALE = 1.35


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


def _even(v: int) -> int:
    """yuv420-safe even dimension, at least 2."""
    v = int(v) - (int(v) % 2)
    return max(v, 2)


def _pad(box: Box, src_w: int, src_h: int) -> Box:
    x = _clamp(box.x, 0, src_w - 8)
    y = _clamp(box.y, 0, src_h - 8)
    w = _even(min(box.w, src_w - x))
    h = _even(min(box.h, src_h - y))
    return Box(x=x, y=y, w=max(w, 8), h=max(h, 8))


def is_closeup_overlay(box: Box, src_w: int, src_h: int) -> bool:
    """True when the overlay is already a tall close-up, not a corner pip."""
    return box.h >= src_h * STACKED_CLOSEUP_MIN_H


def tighten_overlay_box(box: Box, src_w: int, src_h: int) -> Box:
    """Inset an OBS/YouTube-Studio overlay so chat chrome is not in the card.

    Studio live-chat reaction buttons sit on the top edge of a bottom-left
    cam. Expanding a face to 16:9 pulls those icons into the crop.
    """
    top = max(round(box.h * 0.18), 20)
    side = max(round(box.w * 0.05), 8)
    bot = max(round(box.h * 0.04), 4)
    return _pad(
        Box(x=box.x + side, y=box.y + top, w=box.w - 2 * side, h=box.h - top - bot),
        src_w,
        src_h,
    )


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
    in_label: str = "0:v",
    out_label: str = "vpre",
    **_ignored,
) -> tuple[str, Canvas]:
    """Legacy coding-stream template: screen on top, facecam strip below."""
    strip_h = _even(_clamp(strip_h, 320, out_h // 2))
    screen_h = _even(out_h - strip_h)
    cam = _pad(facecam or default_facecam_box(src_w, src_h), src_w, src_h)

    sw, sh, crop_x, crop_y = compute_cover_crop(src_w, src_h, out_w, screen_h, avoid=cam)

    screen = (
        f"[{in_label}]scale=w={sw}:h={sh},crop={out_w}:{screen_h}:{crop_x}:{crop_y},"
        f"setsar=1[screen]"
    )
    camstrip = (
        f"[{in_label}]crop={cam.w}:{cam.h}:{cam.x}:{cam.y},"
        f"scale=w={out_w}:h={strip_h}:force_original_aspect_ratio=decrease,"
        f"pad={out_w}:{strip_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1[camstrip]"
    )
    merge = f"[screen][camstrip]vstack=inputs=2[{out_label}]"
    return ";".join([screen, camstrip, merge]), Canvas(out_w, out_h)


def stacked(
    src_w: int,
    src_h: int,
    facecam: Box | None = None,
    cam_h: int = STACKED_CAM_H,
    screen_h: int = STACKED_SCREEN_H,
    out_w: int = 1080,
    out_h: int = 1920,
    in_label: str = "0:v",
    out_label: str = "vpre",
    **_ignored,
) -> tuple[str, Canvas]:
    """Person+screen Shorts template matching the reference clips.

    Full-canvas darkened blur behind two inset cards (reference Shorts):
    - corner pip: overlay tightened (drops Studio chat chrome), COVER-filled
      with lanczos + unsharp so the card is edge-to-edge face
    - tall close-up overlay (forehead-cam): modest upscale, centered on the
      blur — COVER would macro-crop glasses/pores
    - screen: entire 16:9 desktop fitted, never cover-cropped
    Captions sit on the screen card; leftover canvas is Shorts chrome.
    """
    p = out_label
    cam_h = _even(_clamp(cam_h, 320, out_h - 400))
    screen_h = _even(_clamp(screen_h, 240, out_h - cam_h - STACKED_BOTTOM))
    raw = _pad(facecam or default_facecam_box(src_w, src_h), src_w, src_h)
    closeup = is_closeup_overlay(raw, src_w, src_h)
    if closeup:
        # Light inset drops live-chat chrome sitting on a forehead-cam.
        top = max(round(raw.h * 0.12), 24)
        side = max(round(raw.w * 0.04), 6)
        bot = max(round(raw.h * 0.03), 4)
        cam = _pad(
            Box(x=raw.x + side, y=raw.y + top, w=raw.w - 2 * side, h=raw.h - top - bot),
            src_w,
            src_h,
        )
    else:
        cam = tighten_overlay_box(raw, src_w, src_h)

    margin = STACKED_MARGIN
    gap = STACKED_GAP
    card_w = _even(out_w - 2 * margin)
    cam_y = margin
    scr_y = cam_y + cam_h + gap
    ox = _even((out_w - card_w) // 2)

    bg = (
        f"[{in_label}]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{out_h},scale=iw/12:ih/12,gblur=sigma=14,"
        f"scale={out_w}:{out_h},eq=brightness=-0.18:saturation=0.5,setsar=1[{p}bg]"
    )
    if closeup:
        scale = min(card_w / cam.w, cam_h / cam.h, STACKED_CLOSEUP_MAX_SCALE)
        fit_w = _even(max(int(cam.w * scale), 8))
        fit_h = _even(max(int(cam.h * scale), 8))
        cam_ox = ox + (card_w - fit_w) // 2
        cam_oy = cam_y + (cam_h - fit_h) // 2
        camcard = (
            f"[{in_label}]crop={cam.w}:{cam.h}:{cam.x}:{cam.y},"
            f"scale={fit_w}:{fit_h}:flags=lanczos,"
            f"unsharp=5:5:1.2:3:3:0.4,setsar=1[{p}camcard]"
        )
        cam_overlay = f"[{p}bg][{p}camcard]overlay={cam_ox}:{cam_oy}[{p}tmp]"
    else:
        # COVER the tightened overlay into the cam card (lanczos + unsharp).
        camcard = (
            f"[{in_label}]crop={cam.w}:{cam.h}:{cam.x}:{cam.y},"
            f"scale={card_w}:{cam_h}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={card_w}:{cam_h},unsharp=5:5:1.2:3:3:0.4,setsar=1[{p}camcard]"
        )
        cam_overlay = f"[{p}bg][{p}camcard]overlay={ox}:{cam_y}[{p}tmp]"
    scrcard = (
        f"[{in_label}]scale={card_w}:{screen_h}:force_original_aspect_ratio=decrease"
        f":flags=lanczos,pad={card_w}:{screen_h}:(ow-iw)/2:(oh-ih)/2:black,"
        f"setsar=1[{p}scrcard]"
    )
    merge = (
        f"{cam_overlay};"
        f"[{p}tmp][{p}scrcard]overlay={ox}:{scr_y},setsar=1[{out_label}]"
    )
    return ";".join([bg, camcard, scrcard, merge]), Canvas(out_w, out_h)


def stacked_caption_margin(
    cam_h: int = STACKED_CAM_H,
    screen_h: int = STACKED_SCREEN_H,
    out_h: int = 1920,
) -> int:
    """ASS MarginV so captions sit on the screen card, above Shorts chrome."""
    scr_y = STACKED_MARGIN + cam_h + STACKED_GAP
    y = scr_y + int(screen_h * 0.55)
    return max(220, out_h - y)


def face_crop(
    src_w: int,
    src_h: int,
    facecam: Box | None = None,
    out_w: int = 1080,
    out_h: int = 1920,
    in_label: str = "0:v",
    out_label: str = "vpre",
    **_ignored,
) -> tuple[str, Canvas]:
    """Classic vertical crop centered on the speaker (or frame center)."""
    win_w = _even(min(src_w, round(src_h * out_w / out_h)))
    if facecam is None:
        x = _even((src_w - win_w) // 2)
    else:
        cx = facecam.x + facecam.w / 2
        x = _even(_clamp(round(cx - win_w / 2), 0, src_w - win_w))
    chain = (
        f"[{in_label}]crop={win_w}:{src_h}:{x}:0,"
        f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{out_h},setsar=1[{out_label}]"
    )
    return chain, Canvas(out_w, out_h)


def fullframe(
    src_w: int,
    src_h: int,
    facecam: Box | None = None,
    out_w: int = 1080,
    out_h: int = 1920,
    in_label: str = "0:v",
    out_label: str = "vpre",
    **_ignored,
) -> tuple[str, Canvas]:
    """Camera-only template: one 9:16 view centered on the active speaker."""
    return face_crop(
        src_w, src_h, facecam=facecam, out_w=out_w, out_h=out_h,
        in_label=in_label, out_label=out_label,
    )


def passthrough(
    src_w: int,
    src_h: int,
    facecam: Box | None = None,
    out_w: int = 1920,
    out_h: int = 1080,
    in_label: str = "0:v",
    out_label: str = "vpre",
    **_ignored,
) -> tuple[str, Canvas]:
    """Long-form 16:9 with letterbox padding when needed."""
    chain = (
        f"[{in_label}]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
        f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1[{out_label}]"
    )
    return chain, Canvas(out_w, out_h)


LAYOUTS = {
    "vertical-split": vertical_split,
    "stacked": stacked,
    "face-crop": face_crop,
    "fullframe": fullframe,
    "passthrough": passthrough,
}

SHORTS_LAYOUTS = frozenset({"stacked", "fullframe", "face-crop", "vertical-split"})


def aspect_hint(width: int, height: int) -> str:
    """Human-readable orientation tag used in output naming."""
    r = width / height if height else 1.0
    if math.isclose(r, 16 / 9, rel_tol=0.05):
        return "wide"
    if r < 0.8:
        return "shorts"
    return "square"


def layout_for_mode(mode: str) -> str:
    """Map a scene-classifier mode to the layout an agent should pick."""
    if mode == "cam-only":
        return "fullframe"
    return "stacked"
