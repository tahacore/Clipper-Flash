from clipper_flash.layouts import (
    LAYOUTS,
    Box,
    Canvas,
    aspect_hint,
    compute_cover_crop,
    default_facecam_box,
    face_crop,
    fullframe,
    is_closeup_overlay,
    layout_for_mode,
    passthrough,
    stacked,
    stacked_caption_margin,
    tighten_overlay_box,
    vertical_split,
)


def test_default_facecam_bottom_right() -> None:
    b = default_facecam_box(1920, 1080)
    assert b.x + b.w <= 1920
    assert b.y + b.h <= 1080
    assert b.x > 1920 / 2  # right half


def test_cover_crop_center_when_no_cam() -> None:
    sw, sh, x, y = compute_cover_crop(1920, 1080, 1080, 1280)
    assert (sw, sh) == (2276, 1280)  # scale to cover height
    assert x == (2276 - 1080) // 2
    assert y == 0


def test_cover_crop_avoids_right_side_cam() -> None:
    cam = Box(x=1500, y=800, w=340, h=190)  # bottom-right cam
    sw, sh, x, y = compute_cover_crop(1920, 1080, 1080, 1280, avoid=cam)
    # window shifted left so the cam center is outside it
    ccx = (cam.x + cam.w / 2) * sw / 1920
    assert not (x <= ccx <= x + 1080 and 0 <= (cam.y + cam.h / 2) * sh / 1080 <= 1280)


def test_vertical_split_chain_structure() -> None:
    chain, canvas = vertical_split(1920, 1080)
    assert isinstance(canvas, Canvas) and (canvas.width, canvas.height) == (1080, 1920)
    assert "[screen]" in chain and "[camstrip]" in chain and "vstack" in chain
    assert "crop=" in chain


def test_vertical_split_custom_strip() -> None:
    _, canvas = vertical_split(1280, 720, strip_h=400)
    assert canvas.height == 1920


def test_face_crop_centers_on_cam() -> None:
    cam = Box(x=200, y=600, w=300, h=170)  # left-side cam
    chain, canvas = face_crop(1920, 1080, facecam=cam)
    assert (canvas.width, canvas.height) == (1080, 1920)
    # window (~608px wide) should be shifted toward the left-side cam
    import re as _re

    m = _re.search(r"crop=\d+:1080:(\d+):0", chain)
    assert m, chain
    x = int(m.group(1))
    assert x < 350  # left of cam center (350), not the default center crop


def test_passthrough_letterboxes() -> None:
    chain, canvas = passthrough(1080, 1920)  # vertical source into wide canvas
    assert (canvas.width, canvas.height) == (1920, 1080)
    assert "pad=1920:1080" in chain


def test_aspect_hint() -> None:
    assert aspect_hint(1920, 1080) == "wide"
    assert aspect_hint(1080, 1920) == "shorts"


def test_registry_has_stacked_and_fullframe() -> None:
    assert {"stacked", "fullframe"} <= set(LAYOUTS)


def test_stacked_cards_sit_on_blurred_canvas() -> None:
    cam = Box(x=1452, y=714, w=468, h=366)
    chain, canvas = stacked(1920, 1080, facecam=cam)
    assert (canvas.width, canvas.height) == (1080, 1920)
    assert "gblur" in chain and chain.count("overlay=") >= 2
    assert "flags=lanczos" in chain and "unsharp=" in chain
    assert "eq=brightness=" in chain
    assert "force_original_aspect_ratio=increase:flags=lanczos" in chain  # cam cover
    assert "force_original_aspect_ratio=decrease:flags=lanczos" in chain  # screen fit
    assert "[vpre]" in chain
    assert "pad=1080:1920:0:0:black" not in chain


def test_stacked_screen_zone_never_cover_crops() -> None:
    chain, _ = stacked(2560, 1080, facecam=Box(2000, 800, 400, 240))
    assert "force_original_aspect_ratio=decrease:flags=lanczos" in chain
    assert "[vprescrcard]" in chain


def test_stacked_tightens_overlay_crop() -> None:
    raw = Box(x=0, y=618, w=680, h=384)
    chain, _ = stacked(1920, 1080, facecam=raw)
    tight = tighten_overlay_box(raw, 1920, 1080)
    assert f"crop={tight.w}:{tight.h}:{tight.x}:{tight.y}" in chain


def test_tighten_overlay_drops_studio_chrome() -> None:
    raw = Box(x=0, y=618, w=680, h=384)
    tight = tighten_overlay_box(raw, 1920, 1080)
    assert tight.y >= raw.y + 40
    assert tight.h < raw.h - 30
    assert tight.x > raw.x
    assert tight.w < raw.w


def test_fullframe_centers_on_face() -> None:
    src_w, src_h = 1920, 1080
    face = Box(x=1500, y=700, w=360, h=270)
    chain, canvas = fullframe(src_w, src_h, facecam=face)
    assert (canvas.width, canvas.height) == (1080, 1920)
    import re as _re

    m = _re.search(r"crop=\d+:1080:(\d+):0", chain)
    assert m, chain
    crop_x = int(m.group(1))
    win_w = min(src_w, round(src_h * 1080 / 1920))
    win_w = win_w - win_w % 2
    cx = face.x + face.w / 2
    assert crop_x <= cx <= crop_x + win_w


def test_fullframe_without_box_is_center_not_corner() -> None:
    chain, _ = fullframe(1920, 1080, facecam=None)
    import re as _re

    m = _re.search(r"crop=\d+:1080:(\d+):0", chain)
    assert m, chain
    x = int(m.group(1))
    assert 500 < x < 800  # centered, not the default bottom-right cam


def test_stacked_caption_margin_clears_shorts_chrome() -> None:
    mv = stacked_caption_margin()
    assert mv >= 280


def test_layout_for_mode() -> None:
    assert layout_for_mode("cam-only") == "fullframe"
    assert layout_for_mode("screen+cam") == "stacked"
    assert layout_for_mode("screen") == "stacked"


def test_closeup_overlay_is_tall_not_corner_pip() -> None:
    corner = Box(x=1452, y=714, w=468, h=366)
    forehead = Box(x=1450, y=530, w=470, h=550)
    assert not is_closeup_overlay(corner, 1920, 1080)
    assert is_closeup_overlay(forehead, 1920, 1080)


def test_stacked_closeup_does_not_cover_fill() -> None:
    cam = Box(x=1450, y=530, w=470, h=550)
    chain, _ = stacked(1920, 1080, facecam=cam)
    assert "force_original_aspect_ratio=increase:flags=lanczos" not in chain
    assert "scale=" in chain and "flags=lanczos" in chain
    # inset from the raw overlay (live-chat chrome on the top edge)
    assert f"crop={cam.w}:{cam.h}:{cam.x}:{cam.y}" not in chain
    # overlay is not pinned to the top-left of the cam slot (24, 24)
    assert "overlay=24:24[" not in chain


def test_stacked_corner_cam_still_cover_fills() -> None:
    cam = Box(x=1452, y=714, w=468, h=366)
    chain, _ = stacked(1920, 1080, facecam=cam)
    assert "force_original_aspect_ratio=increase:flags=lanczos" in chain


def test_stacked_custom_labels_for_segments() -> None:
    chain, _ = stacked(1920, 1080, in_label="1:v", out_label="v1")
    assert "[1:v]" in chain and "[v1]" in chain
    assert "[vpre]" not in chain
