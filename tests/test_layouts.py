from clipper_flash.layouts import (
    Box,
    Canvas,
    aspect_hint,
    compute_cover_crop,
    default_facecam_box,
    face_crop,
    passthrough,
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
