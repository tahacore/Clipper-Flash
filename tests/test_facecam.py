import pytest

from clipper_flash.facecam import FacecamNotFound, find_stable_box

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
