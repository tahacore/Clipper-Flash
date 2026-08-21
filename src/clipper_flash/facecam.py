"""Facecam region detection.

A streamer's facecam sits in a fixed corner for the whole stream, so we don't
need tracking - just a few sampled frames and a vote. Sample N frames evenly,
detect faces in each, and keep the box that appears consistently in the same
place. Detectors: MediaPipe (preferred), OpenCV Haar fallback.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


class FacecamNotFound(RuntimeError):
    pass


@dataclass
class Facecam:
    x: int
    y: int
    w: int
    h: int
    confidence: float  # fraction of sampled frames that voted for this box

    def to_dict(self) -> dict:
        return asdict(self)


# --- pure voting logic (unit-testable) ---------------------------------------


def find_stable_box(
    boxes_per_frame: list[list[tuple[float, float, float, float]]],
    src_w: int,
    src_h: int,
    min_votes_frac: float = 0.4,
    grid: float = 0.05,
) -> Facecam:
    """Vote for the most consistent normalized box across frames.

    boxes_per_frame: per-frame lists of (nx, ny, nw, nh) normalized boxes.
    """
    total = len(boxes_per_frame)
    if total == 0:
        raise FacecamNotFound("no frames sampled")

    buckets: dict[tuple[int, int], list[tuple[float, float, float, float]]] = {}
    gx, gy = max(1, round(1 / grid)), max(1, round(1 / grid))
    for boxes in boxes_per_frame:
        seen_cells: set[tuple[int, int]] = set()
        for nx, ny, nw, nh in boxes:
            cx, cy = nx + nw / 2, ny + nh / 2
            cell = (int(cx * gx), int(cy * gy))
            if cell in seen_cells:
                continue
            seen_cells.add(cell)
            buckets.setdefault(cell, []).append((nx, ny, nw, nh))

    best_cell, votes = max(buckets.items(), key=lambda kv: len(kv[1]), default=(None, []))
    if not votes or len(votes) / total < min_votes_frac:
        raise FacecamNotFound(
            f"no stable facecam region (best {len(votes)}/{total} frames)"
        )

    xs = sorted(v[0] for v in votes)
    ys = sorted(v[1] for v in votes)
    ws = sorted(v[2] for v in votes)
    hs = sorted(v[3] for v in votes)

    def median(seq: list[float]) -> float:
        n = len(seq)
        return seq[n // 2] if n % 2 else (seq[n // 2 - 1] + seq[n // 2]) / 2

    nx, ny, nw, nh = median(xs), median(ys), median(ws), median(hs)
    return Facecam(
        x=max(0, round(nx * src_w)),
        y=max(0, round(ny * src_h)),
        w=min(round(nw * src_w), src_w),
        h=min(round(nh * src_h), src_h),
        confidence=round(len(votes) / total, 3),
    )


# --- detectors ---------------------------------------------------------------


def _mediapipe_detect(frame_rgb) -> list[tuple[float, float, float, float]]:
    import mediapipe as mp

    with mp.solutions.face_detection.FaceDetection(
        model_selection=1, min_detection_confidence=0.5
    ) as fd:
        res = fd.process(frame_rgb)
    out = []
    if res.detections:
        for d in res.detections:
            b = d.location_data.relative_bounding_box
            out.append((b.xmin, b.ymin, b.width, b.height))
    return out


def _haar_detect(frame_bgr) -> list[tuple[float, float, float, float]]:
    import cv2

    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(cascade_path)
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(48, 48))
    h, w = gray.shape[:2]
    return [(x / w, y / h, fw / w, fh / h) for x, y, fw, fh in faces]


def sample_and_detect(
    video_path: str,
    samples: int = 12,
    detector=None,
) -> tuple[list[list[tuple[float, float, float, float]]], tuple[int, int]]:
    """Sample frames evenly and run the detector on each."""
    import cv2

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FacecamNotFound(f"cannot open video: {video_path}")
    try:
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        if frames <= 0:
            raise FacecamNotFound("cannot determine video length")
        src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        if detector is None:
            try:
                _mediapipe_detect.__globals__["mp"]  # probe availability
                detector = _mediapipe_detect
            except Exception:  # noqa: BLE001
                detector = _haar_detect

        per_frame: list[list[tuple[float, float, float, float]]] = []
        margin = 0.02
        for i in range(samples):
            t = (margin + (1 - 2 * margin) * i / max(samples - 1, 1)) * frames
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(t))
            ok, frame = cap.read()
            if not ok:
                continue
            try:
                boxes = detector(frame)
            except Exception:  # noqa: BLE001 - a bad frame must not kill detection
                boxes = []
            per_frame.append(boxes)
        return per_frame, (src_w, src_h)
    finally:
        cap.release()


def detect_facecam(video_path: str, samples: int = 12, detector=None) -> Facecam:
    """High-level API: video path -> stable facecam box (pixels)."""
    per_frame, (src_w, src_h) = sample_and_detect(video_path, samples=samples, detector=detector)
    return find_stable_box(per_frame, src_w, src_h)
