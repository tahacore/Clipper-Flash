from clipper_flash.scenes import (
    Sample,
    build_scene_map,
    classify_sample,
    dominant_face,
    merge_hysteresis,
    shot_boundaries,
)

OVERLAY = (0.72, 0.62, 0.22, 0.24)  # small corner cam
CLOSEUP = (0.30, 0.10, 0.40, 0.55)  # face fills the frame
GUEST = (0.10, 0.12, 0.38, 0.50)


def test_classify_overlay_vs_closeup_vs_empty() -> None:
    assert classify_sample([OVERLAY]) == "screen+cam"
    assert classify_sample([CLOSEUP]) == "cam-only"
    assert classify_sample([]) == "screen"


def test_hysteresis_absorbs_short_flaps() -> None:
    # 0-4 screen+cam, 4-5 cam-only blip, 5-12 screen+cam
    timed = (
        [(t, "screen+cam") for t in (0.0, 1.0, 2.0, 3.0)]
        + [(4.0, "cam-only")]
        + [(t, "screen+cam") for t in (5.0, 6.0, 8.0, 11.0)]
    )
    runs = merge_hysteresis(timed, min_dur=3.0, end_t=12.0)
    assert len(runs) == 1
    assert runs[0][2] == "screen+cam"
    assert runs[0][0] == 0.0
    assert runs[0][1] == 12.0


def test_hysteresis_keeps_long_mode_changes() -> None:
    timed = [(t, "screen+cam") for t in range(0, 6)] + [(t, "cam-only") for t in range(6, 14)]
    runs = merge_hysteresis([(float(t), m) for t, m in timed], min_dur=3.0, end_t=14.0)
    assert [r[2] for r in runs] == ["screen+cam", "cam-only"]
    assert runs[1][0] == 6.0


def test_shot_boundaries_ignore_small_diffs() -> None:
    samples = [
        Sample(0.0, [CLOSEUP], diff=0.0),
        Sample(0.5, [CLOSEUP], diff=2.0),
        Sample(1.0, [CLOSEUP], diff=3.0),
        Sample(2.5, [GUEST], diff=40.0),
        Sample(3.0, [GUEST], diff=4.0),
    ]
    cuts = shot_boundaries(samples, threshold=18.0, min_shot=1.2)
    assert cuts[0] == 0.0
    assert 2.5 in cuts


def test_dominant_face_picks_median_largest() -> None:
    boxes = [
        [OVERLAY, CLOSEUP],
        [CLOSEUP],
        [GUEST, CLOSEUP],
    ]
    face = dominant_face(boxes)
    assert face is not None
    # CLOSEUP area wins
    assert face[2] == 0.40 and face[3] == 0.55


def test_build_scene_map_splits_cam_only_on_shots() -> None:
    samples = []
    for t in [i * 0.5 for i in range(0, 10)]:  # 0-5s overlay
        samples.append(Sample(t, [OVERLAY], diff=1.0))
    for t in [i * 0.5 for i in range(10, 20)]:  # 5-10s speaker A
        samples.append(Sample(t, [CLOSEUP], diff=2.0 if t != 5.0 else 1.0))
    samples[10].diff = 1.0
    samples.append(Sample(10.0, [GUEST], diff=45.0))  # cut to speaker B
    for t in [i * 0.5 for i in range(21, 30)]:
        samples.append(Sample(t, [GUEST], diff=2.0))
    segs = build_scene_map(samples, src_w=1920, src_h=1080, duration=15.0, min_dur=2.5)
    modes = [s.mode for s in segs]
    assert "screen+cam" in modes
    assert "cam-only" in modes
    cam_only = [s for s in segs if s.mode == "cam-only"]
    assert len(cam_only) >= 2
    assert cam_only[0].layout == "fullframe"
    assert cam_only[0].face is not None
    assert segs[0].layout == "stacked"
