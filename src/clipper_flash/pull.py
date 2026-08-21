"""yt-dlp download wrappers: exact clip sections and audio-only pulls.

Key trick: `--download-sections` fetches only the requested range, and
`--force-keyframes-at-cuts` makes the boundaries frame-exact (small boundary
re-encode). A 60s section costs seconds instead of pulling an 8-hour VOD.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


class PullError(RuntimeError):
    pass


@dataclass
class PullResult:
    path: str
    start_sec: float
    end_sec: float
    kind: str  # "section" | "audio"


def parse_time(value: str | float) -> float:
    """Accept '90', '1:30', '1:23:00.5' -> seconds."""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if re.fullmatch(r"[\d.]+", s):
        return float(s)
    parts = s.split(":")
    if not 1 < len(parts) <= 3:
        raise ValueError(f"bad time format: {value!r}")
    try:
        nums = [float(p) for p in parts]
    except ValueError as exc:
        raise ValueError(f"bad time format: {value!r}") from exc
    while len(nums) < 3:
        nums.insert(0, 0.0)
    h, m, sec = nums
    return h * 3600 + m * 60 + sec


def fmt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:06.3f}"


def _run_ytdlp(args: list[str]) -> dict:
    cmd = [sys.executable, "-m", "yt_dlp", *args, "--no-warnings", "--progress"]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise PullError(f"yt-dlp failed ({proc.returncode}):\n{proc.stderr[-2000:]}")
    # last JSON line printed by --print after_move_filepath / info-json
    for line in reversed(proc.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    return {}


def pull_section(
    url: str,
    start_sec: float,
    end_sec: float,
    out_path: str | Path,
    max_height: int = 1080,
) -> PullResult:
    """Download exactly [start_sec, end_sec] at best quality <= max_height."""
    if end_sec <= start_sec:
        raise PullError(f"end ({end_sec}) must be after start ({start_sec})")
    if end_sec - start_sec > 15 * 60:
        raise PullError("section longer than 15 minutes - split it")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    section = f"*{fmt_time(start_sec)}-{fmt_time(end_sec)}"

    args = [
        "--download-sections", section,
        "--force-keyframes-at-cuts",
        "-f", f"bv*[height<={max_height}][ext=mp4]+ba[ext=m4a]/b[height<={max_height}]/bv*+ba/b",
        "--merge-output-format", "mp4",
        "--print", "after_move:filepath",
        "-o", str(out_path),
        url,
    ]
    result = _run_ytdlp(args)
    final = result.get("filepath") or str(out_path)
    produced = Path(final)
    if not produced.exists():
        raise PullError(f"expected output missing: {produced}")
    return PullResult(path=str(produced), start_sec=start_sec, end_sec=end_sec, kind="section")


def pull_audio(url: str, out_path: str | Path) -> PullResult:
    """Download audio-only track (m4a). Used for offline transcription fallback."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "-f", "ba[ext=m4a]/ba/b",
        "--print", "after_move:filepath",
        "-o", str(out_path),
        url,
    ]
    result = _run_ytdlp(args)
    final = result.get("filepath") or str(out_path)
    produced = Path(final)
    if not produced.exists():
        raise PullError(f"expected output missing: {produced}")
    return PullResult(path=str(produced), start_sec=0.0, end_sec=0.0, kind="audio")
