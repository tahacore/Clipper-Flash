"""ASS subtitle generation for burned-in clip captions.

Words come from the cleaned transcript (absolute stream time). We group them
into short readable lines, shift times into clip-relative time, and emit a
styled .ass file sized for the target canvas.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MAX_LINE_WORDS = 6
MAX_LINE_SECONDS = 2.4
LINE_BREAK_GAP = 0.5

STYLES: dict[str, dict] = {
    # font_size tuned for 1080-wide canvases
    "bold": {"font": "Arial Black", "size": 58, "primary": "&H00FFFFFF", "outline": "&H00000000",
             "outline_w": 4, "bold": 1, "margin_v": 60},
    "clean": {"font": "Arial", "size": 52, "primary": "&H00FFFFFF", "outline": "&H00202020",
              "outline_w": 3, "bold": 0, "margin_v": 60},
}


@dataclass
class CaptionLine:
    start: float  # clip-relative seconds
    end: float
    text: str


def group_words_into_lines(
    words: list[dict], clip_start: float, clip_end: float
) -> list[CaptionLine]:
    """words: [{'start','end','text'}] in ABSOLUTE stream time."""
    rel = [
        w for w in words
        if w["end"] > clip_start and w["start"] < clip_end
    ]
    lines: list[CaptionLine] = []
    bucket: list[dict] = []

    def flush() -> None:
        if not bucket:
            return
        text = " ".join(str(w["text"]).strip() for w in bucket).strip()
        if text:
            lines.append(
                CaptionLine(
                    start=max(bucket[0]["start"] - clip_start, 0.0),
                    end=min(bucket[-1]["end"] - clip_start, clip_end - clip_start),
                    text=text,
                )
            )
        bucket.clear()

    for w in rel:
        if bucket:
            gap = w["start"] - bucket[-1]["end"]
            span = w["end"] - bucket[0]["start"]
            if gap > LINE_BREAK_GAP or span > MAX_LINE_SECONDS or len(bucket) >= MAX_LINE_WORDS:
                flush()
        bucket.append(w)
    flush()
    return lines


def _ass_time(seconds: float) -> str:
    s = max(0.0, seconds)
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h}:{m:02d}:{sec:05.2f}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def build_ass(
    lines: list[CaptionLine],
    out_path: str | Path,
    width: int,
    height: int,
    style: str = "bold",
    margin_v_override: int | None = None,
) -> Path:
    st = STYLES.get(style, STYLES["bold"])
    margin_v = margin_v_override if margin_v_override is not None else st["margin_v"]
    fmt_line = (
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
    )
    style_line = (
        f"Style: Cap,{st['font']},{st['size']},{st['primary']},&H000000FF,{st['outline']},"
        f"&H80000000,{st['bold']},0,0,0,100,100,0,0,1,{st['outline_w']},2,2,60,60,"
        f"{margin_v},1"
    )
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
{fmt_line}
{style_line}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = [
        f"Dialogue: 0,{_ass_time(line.start)},{_ass_time(max(line.end, line.start + 0.3))},"
        f"Cap,,0,0,0,,{_escape(line.text)}"
        for line in lines
    ]
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return out_path


def make_captions_for_clip(
    transcript_words: list[dict],
    abs_start: float,
    clip_start: float,
    clip_end: float,
    out_path: str | Path,
    width: int,
    height: int,
    style: str = "bold",
    margin_v_override: int | None = None,
) -> Path:
    """Convenience: absolute-time words -> styled .ass for one clip."""
    lines = group_words_into_lines(transcript_words, abs_start + clip_start, abs_start + clip_end)
    return build_ass(lines, out_path, width, height, style, margin_v_override)
