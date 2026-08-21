import pytest

from clipper_flash.facecam import (
    FacecamNotFound,
    detect_facecam,
    expand_face_to_cam,
    find_stable_box,
    make_yunet_detector,
)

CAM = (0.70, 0.60, 0.20, 0.30)  # bottom-right facecam, normalized


def per_frame(n, cam=CAM, noise=0.0):
    frames = []
    for i in range(n):
        jitter = noise * ((-1) ** i)
        frames.append([(cam[0] + jitter, cam[1], cam[2], cam[3])])
    return frames


def test_stable_box_wins_with_full_votes() -> None:
    fc = find_stable_box(per_frame(10), 1920, 1080)
    assert fc.confidence == 1.0
    assert fc.x == pytest.approx(0.70 * 1920, abs=2)
    assert fc.y == pytest.approx(0.60 * 1080, abs=2)
    assert fc.w == pytest.approx(0.20 * 1920, abs=2)


def test_noisy_frames_still_cluster() -> None:
    boxes = []
    for i in range(12):
        if i % 3 == 0:
            boxes.append([])  # detector missed these frames
        else:
            boxes.append([CAM])
    fc = find_stable_box(boxes, 1920, 1080)
    assert fc.confidence == pytest.approx(8 / 12, abs=0.01)


def test_below_vote_threshold_raises() -> None:
    # every frame has a face somewhere different -> nothing is stable
    boxes = [
        [(0.05 + i * 0.05, 0.05, 0.1, 0.1)] for i in range(10)
    ]
    with pytest.raises(FacecamNotFound):
        find_stable_box(boxes, 1920, 1080)


def test_empty_input_raises() -> None:
    with pytest.raises(FacecamNotFound):
        find_stable_box([], 1920, 1080)


def test_two_faces_picks_consistent_one() -> None:
    boxes = [[CAM, (0.05, 0.05, 0.15, 0.15)] for _ in range(6)]
    fc = find_stable_box(boxes, 1920, 1080)
    assert fc.x > 1000  # the corner cam wins


def test_yunet_detector_loads_and_runs() -> None:
    """The bundled yunet model must load and run on a blank frame."""
    det = make_yunet_detector()
    if det is None:
        pytest.skip("opencv or bundled model unavailable")
    import numpy as np

    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    result = det(blank)
    assert isinstance(result, list)  # no faces on blank - but no crash


def tiny_video(path, frames=10, w=64, h=64) -> None:
    """Write a real (openable) video so VideoCapture works in tests."""
    import cv2
    import numpy as np

    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (w, h))
    for _ in range(frames):
        vw.write(np.zeros((h, w, 3), dtype=np.uint8))
    vw.release()


def test_expand_face_to_cam_window() -> None:
    """Face box grows into a ~16:9 cam window, clamped to the frame."""
    from clipper_flash.facecam import Facecam

    face = Facecam(x=277, y=707, w=105, h=152, confidence=0.9)
    cam = expand_face_to_cam(face, 1920, 1080)
    # bigger than the face, roughly 16:9, inside the frame
    assert cam.w > face.w * 2 and cam.h > face.h * 1.5
    assert cam.w / cam.h > 1.5  # landscape-ish window
    assert cam.x >= 0 and cam.y >= 0
    assert cam.x + cam.w <= 1920 and cam.y + cam.h <= 1080
    assert cam.confidence == 0.9


def test_all_detector_errors_reported_as_broken(tmp_path) -> None:
    """A crashing detector must say 'stack broken', not 'no faces'."""
    video = tmp_path / "tiny.avi"
    tiny_video(video)

    def boom(frame):
        raise RuntimeError("detector gone")

    with pytest.raises(FacecamNotFound, match="vision stack is broken"):
        detect_facecam(str(video), samples=3, detector=boom)


def test_partial_detector_errors_still_detect(tmp_path) -> None:
    """Some erroring frames must not kill detection if others vote."""
    calls = {"n": 0}

    def flaky(frame):
        calls["n"] += 1
        if calls["n"] % 2 == 0:
            raise RuntimeError("boom")
        return [CAM]

    video = tmp_path / "tiny.avi"
    tiny_video(video)
    fc = detect_facecam(str(video), samples=4, detector=flaky)
    assert fc.confidence == pytest.approx(0.5)  # half the frames voted CAM
