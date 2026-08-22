"""Scene classification for a pulled section.

A coding stream is mostly `screen+cam` (small overlay face). A podcast or
cam-only beat is `cam-only` (face fills the frame). Shot cuts inside
cam-only stretches give us speaker switches without audio diarization.

Pure functions take precomputed samples so tests stay offline. Network/IO
lives in `analyze_video`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from clipper_flash.layouts import layout_for_mode

CLOSEUP_FACE_H = 0.28  # face height as fraction of frame → cam-only
MIN_SEGMENT_SEC = 3.0
SHOT_DIFF_THRESHOLD = 18.0  # mean abs pixel diff on a 64×36 gray frame
MIN_SHOT_SEC = 1.2
SAMPLE_FPS = 2.0


class SceneError(RuntimeError):
    pass


@dataclass
class Sample:
    t: float
    boxes: list[tuple[float, float, float, float]]  # normalized nx,ny,nw,nh
    diff: float = 0.0  # frame-to-frame gray diff, 0 on first sample


@dataclass
class SceneSegment:
    start: float
    end: float
    mode: str  # "screen+cam" | "cam-only" | "screen"
    layout: str
    face: dict | None = None  # pixel box {x,y,w,h} or None
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def classify_sample(
    boxes: list[tuple[float, float, float, float]],
    closeup_frac: float = CLOSEUP_FACE_H,
) -> str:
    """One sampled frame → mode.

    No faces: `screen` (slides / BRB / desktop). A face taller than
    `closeup_frac` of the frame is a talking-head. Anything smaller is the
    overlay cam on a desktop.
    """
    if not boxes:
        return "screen"
    max_h = max(b[3] for b in boxes)
    if max_h >= closeup_frac:
        return "cam-only"
    return "screen+cam"


def merge_hysteresis(
    timed_modes: list[tuple[float, str]],
    min_dur: float = MIN_SEGMENT_SEC,
    end_t: float | None = None,
) -> list[tuple[float, float, str]]:
    """Stitch consecutive same-mode samples, then absorb blips shorter than min_dur."""
    if not timed_modes:
        return []
    runs: list[list] = []  # [start, end, mode]
    t0, m0 = timed_modes[0]
    start, mode = t0, m0
    prev_t = t0
    for t, m in timed_modes[1:]:
        if m != mode:
            runs.append([start, t, mode])
            start, mode = t, m
        prev_t = t
    last_end = end_t if end_t is not None else prev_t
    runs.append([start, max(last_end, start), mode])

    # absorb short runs into the previous (or next if first)
    i = 0
    while i < len(runs):
        s, e, m = runs[i]
        if e - s + 1e-6 >= min_dur or len(runs) == 1:
            i += 1
            continue
        if i > 0:
            runs[i - 1][1] = e
            del runs[i]
            # collapse if prev now matches next
            if i < len(runs) and runs[i - 1][2] == runs[i][2]:
                runs[i - 1][1] = runs[i][1]
                del runs[i]
            continue
        # first run is short: merge into next
        if i + 1 < len(runs):
            runs[i + 1][0] = s
            del runs[i]
            continue
        i += 1
    return [(float(s), float(e), str(m)) for s, e, m in runs]


def shot_boundaries(
    samples: list[Sample],
    threshold: float = SHOT_DIFF_THRESHOLD,
    min_shot: float = MIN_SHOT_SEC,
) -> list[float]:
    """Timestamps where a new shot starts (includes 0)."""
    cuts = [samples[0].t if samples else 0.0]
    last = cuts[0]
    for s in samples:
        if s.diff >= threshold and (s.t - last) >= min_shot:
            cuts.append(s.t)
            last = s.t
    return cuts


def dominant_face(
    boxes_per_sample: list[list[tuple[float, float, float, float]]],
) -> tuple[float, float, float, float] | None:
    """Median-largest face across samples, returned as normalized (x,y,w,h)."""
    biggest: list[tuple[float, float, float, float]] = []
    for boxes in boxes_per_sample:
        if not boxes:
            continue
        biggest.append(max(boxes, key=lambda b: b[2] * b[3]))
    if not biggest:
        return None

    def med(vals: list[float]) -> float:
        s = sorted(vals)
        n = len(s)
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

    return (
        med([b[0] for b in biggest]),
        med([b[1] for b in biggest]),
        med([b[2] for b in biggest]),
        med([b[3] for b in biggest]),
    )


def _norm_to_px(
    box: tuple[float, float, float, float] | None, src_w: int, src_h: int
) -> dict | None:
    if box is None:
        return None
    nx, ny, nw, nh = box
    return {
        "x": max(0, round(nx * src_w)),
        "y": max(0, round(ny * src_h)),
        "w": max(1, min(round(nw * src_w), src_w)),
        "h": max(1, min(round(nh * src_h), src_h)),
    }


def build_scene_map(
    samples: list[Sample],
    src_w: int,
    src_h: int,
    duration: float,
    closeup_frac: float = CLOSEUP_FACE_H,
    min_dur: float = MIN_SEGMENT_SEC,
    shot_threshold: float = SHOT_DIFF_THRESHOLD,
) -> list[SceneSegment]:
    """Samples → hysteresis-merged mode runs, cam-only split on shot cuts."""
    if not samples:
        return []
    timed = [(s.t, classify_sample(s.boxes, closeup_frac)) for s in samples]
    runs = merge_hysteresis(timed, min_dur=min_dur, end_t=duration)
    cuts = shot_boundaries(samples, threshold=shot_threshold)

    out: list[SceneSegment] = []
    for start, end, mode in runs:
        if mode != "cam-only":
            face = dominant_face([s.boxes for s in samples if start <= s.t < end])
            n = sum(1 for s in samples if start <= s.t < end and s.boxes)
            tot = max(1, sum(1 for s in samples if start <= s.t < end))
            out.append(SceneSegment(
                start=round(start, 3),
                end=round(end, 3),
                mode=mode,
                layout=layout_for_mode(mode),
                face=_norm_to_px(face, src_w, src_h),
                confidence=round(n / tot, 3),
            ))
            continue
        # split cam-only on shot cuts so each speaker hold gets its own face
        interior = [c for c in cuts if start + min_dur * 0.25 < c < end - min_dur * 0.25]
        bounds = [start, *interior, end]
        for a, b in zip(bounds[:-1], bounds[1:], strict=True):
            if b - a < 0.4:
                continue
            face = dominant_face([s.boxes for s in samples if a <= s.t < b])
            n = sum(1 for s in samples if a <= s.t < b and s.boxes)
            tot = max(1, sum(1 for s in samples if a <= s.t < b))
            out.append(SceneSegment(
                start=round(a, 3),
                end=round(b, 3),
                mode="cam-only",
                layout="fullframe",
                face=_norm_to_px(face, src_w, src_h),
                confidence=round(n / tot, 3),
            ))
    return out


def _gray_thumb(frame, w: int = 64, h: int = 36):
    import cv2

    small = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)


def analyze_video(
    video_path: str,
    sample_fps: float = SAMPLE_FPS,
    detector=None,
) -> list[SceneSegment]:
    """Open a section, sample ~sample_fps, return a scene map."""
    import cv2
    import numpy as np

    from clipper_flash.facecam import pick_detector

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise SceneError(f"cannot open video: {video_path}")
    try:
        src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 0
        src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 0
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0) or 30.0
        nframes = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = nframes / fps if nframes > 0 else 0.0
        if src_w <= 0 or src_h <= 0 or duration < 0.5:
            raise SceneError("cannot determine video geometry/duration")

        if detector is None:
            detector, _name = pick_detector()

        step = 1.0 / max(sample_fps, 0.5)
        samples: list[Sample] = []
        prev = None
        t = 0.0
        while t < duration:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok:
                t += step
                continue
            try:
                boxes = detector(frame) or []
            except Exception:  # noqa: BLE001
                boxes = []
            thumb = _gray_thumb(frame)
            diff = 0.0
            if prev is not None:
                diff = float(np.mean(cv2.absdiff(thumb, prev)))
            samples.append(Sample(t=round(t, 3), boxes=list(boxes), diff=diff))
            prev = thumb
            t += step
    finally:
        cap.release()

    if not samples:
        raise SceneError("no frames sampled")
    return build_scene_map(samples, src_w, src_h, duration)
