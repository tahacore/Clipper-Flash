"""Facecam region detection.

A streamer's facecam sits in a fixed corner for the whole stream, so we don't
need tracking - just a few sampled frames and a vote. Sample N frames evenly,
detect faces in each, and keep the box that appears consistently in the same
place. Detector: OpenCV YuNet (model bundled with the package).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

_YUNET_MODEL = Path(__file__).parent / "models" / "face_detection_yunet_2023mar.onnx"


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


def make_yunet_detector():
    """OpenCV YuNet face detector (cv2.FaceDetectorYN + bundled model).

    Works on OpenCV 4.5.4+ and 5.x. Returns None if cv2 or model missing.
    """
    try:
        import cv2
    except Exception:  # noqa: BLE001
        return None
    if not _YUNET_MODEL.exists():
        return None

    def detect(frame_bgr):
        h, w = frame_bgr.shape[:2]
        det = cv2.FaceDetectorYN.create(str(_YUNET_MODEL), "", (w, h), score_threshold=0.6)
        _, faces = det.detect(frame_bgr)
        out = []
        if faces is not None:
            for f in faces:
                x, y, fw, fh, score = f[0], f[1], f[2], f[3], f[14]
                if score >= 0.6:
                    out.append((x / w, y / h, fw / w, fh / h))
        return out

    # sanity check on a tiny frame; a broken stack fails here, not per-video
    import numpy as np

    detect(np.zeros((64, 64, 3), dtype=np.uint8))
    return detect


def pick_detector() -> tuple:
    """Choose the best working detector. Returns (callable, name)."""
    det = make_yunet_detector()
    if det is not None:
        return det, "yunet"
    raise FacecamNotFound(
        "no usable face detector - install vision extras: "
        "uv tool install --force 'clipper-flash[vision]' "
        "(needs opencv-python-headless and the bundled yunet model)"
    )


def sample_and_detect(
    video_path: str,
    samples: int = 12,
    detector=None,
) -> tuple[list[list[tuple[float, float, float, float]]], tuple[int, int], dict]:
    """Sample frames evenly and run the detector on each.

    Returns (per_frame_boxes, (src_w, src_h), info) where info reports which
    detector ran and how many frames errored (vs. legitimately finding none).
    """
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

        name = "custom"
        if detector is None:
            detector, name = pick_detector()

        per_frame: list[list[tuple[float, float, float, float]]] = []
        errors = 0
        margin = 0.02
        for i in range(samples):
            t = (margin + (1 - 2 * margin) * i / max(samples - 1, 1)) * frames
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(t))
            ok, frame = cap.read()
            if not ok:
                continue
            try:
                boxes = detector(frame)
            except Exception:  # noqa: BLE001 - count, don't hide
                errors += 1
                boxes = []
            per_frame.append(boxes)
        return per_frame, (src_w, src_h), {"detector": name, "errors": errors}
    finally:
        cap.release()


def expand_face_to_cam(face: Facecam, src_w: int, src_h: int) -> Facecam:
    """Expand a detected face box into an estimated webcam-window box.

    Detectors return the FACE; layouts want the cam overlay region (head +
    shoulders + some breathing room, roughly 16:9 like an OBS cam source).
    """
    fx, fy = face.x + face.w / 2, face.y + face.h / 2
    cam_h = min(face.h * 2.4, src_h)
    cam_w = min(cam_h * 16 / 9, src_w)
    cam_h = min(cam_w * 9 / 16, src_h)  # re-derive after width clamp
    x = _clamp(int(fx - cam_w / 2), 0, src_w - round(cam_w))
    # bias upward: faces sit in the upper half of a typical cam window
    y = _clamp(int(fy - cam_h * 0.45), 0, src_h - round(cam_h))
    return Facecam(x=x, y=y, w=round(cam_w), h=round(cam_h), confidence=face.confidence)


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def detect_facecam(video_path: str, samples: int = 12, detector=None) -> Facecam:
    """High-level API: video path -> stable facecam box (pixels).

    Returns the estimated cam WINDOW (expanded from the face), which is what
    layout engines should crop.
    """
    per_frame, (src_w, src_h), info = sample_and_detect(
        video_path, samples=samples, detector=detector
    )
    try:
        face = find_stable_box(per_frame, src_w, src_h)
    except FacecamNotFound:
        if info["errors"] and info["errors"] >= len(per_frame):
            raise FacecamNotFound(
                f"face detector errored on {info['errors']}/{len(per_frame)} frames "
                f"({info['detector']}) - vision stack is broken, not faceless. "
                "Fix: uv tool install --force 'clipper-flash[vision]'"
            ) from None
        raise
    return expand_face_to_cam(face, src_w, src_h)
