"""ASS caption generation - the style engine.

Two rendering modes:
- reveal (default): words appear one at a time, active word highlighted.
  The TikTok/CapCut look. Built from word-level timings we already have.
- static: whole line appears at once (legacy behavior).

Style packs tune font/colors/animation. Emphasis words (chosen by the agent,
since it actually read the transcript) get permanent highlight treatment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

MAX_LINE_WORDS = 6
MAX_LINE_SECONDS = 2.4
LINE_BREAK_GAP = 0.5

# ASS colors are &HBBGGRR&
STYLE_PACKS: dict[str, dict] = {
    "hype": {
        "font": "Arial Black", "size": 62, "primary": "&H00FFFFFF",
        "active": "&H0000FFFF",      # yellow pop on the spoken word
        "emphasis": "&H0000D7FF",    # golden for agent-marked words
        "outline": "&H00000000", "outline_w": 4, "bold": 1,
        "margin_v": 60, "mode": "reveal",
    },
    "clean": {
        "font": "Arial", "size": 54, "primary": "&H00FFFFFF",
        "active": "&H0000FFFF",
        "emphasis": "&H0000D7FF",
        "outline": "&H00202020", "outline_w": 3, "bold": 0,
        "margin_v": 60, "mode": "reveal",
    },
    "bold-box": {
        "font": "Arial Black", "size": 56, "primary": "&H00FFFFFF",
        "active": "&H0000FFFF",
        "emphasis": "&H0000D7FF",
        "outline": "&H00000000", "outline_w": 0, "bold": 1,
        "margin_v": 60, "box": True, "mode": "reveal",
    },
    "karaoke-fill": {
        "font": "Arial Black", "size": 58, "primary": "&H00FFFFFF",
        "secondary": "&H00888888",   # un-sung color swept by \k tags
        "active": "&H0000FFFF",
        "emphasis": "&H0000D7FF",
        "outline": "&H00000000", "outline_w": 4, "bold": 1,
        "margin_v": 60, "mode": "karaoke",
    },
    # legacy names keep working
    "bold": {
        "font": "Arial Black", "size": 58, "primary": "&H00FFFFFF",
        "active": "&H00FFFFFF",      # no visible pop -> behaves like static
        "emphasis": "&H0000D7FF",
        "outline": "&H00000000", "outline_w": 4, "bold": 1,
        "margin_v": 60, "mode": "static",
    },
}
STATIC_STYLES = {"minimal"}  # plain line mode, no reveal
STYLE_PACKS["minimal"] = {
    "font": "Arial", "size": 40, "primary": "&H00E8E8E8",
    "active": "&H00E8E8E8", "emphasis": "&H00FFFFFF",
    "outline": "&H00000000", "outline_w": 2, "bold": 0,
    "margin_v": 60, "mode": "static",
}


@dataclass
class CaptionLine:
    start: float  # clip-relative seconds
    end: float
    words: list[dict]  # [{start,end,text}] clip-relative


def group_words_into_lines(
    words: list[dict], clip_start: float, clip_end: float
) -> list[CaptionLine]:
    """words: [{'start','end','text'}] in ABSOLUTE stream time."""
    rel = [
        {"start": w["start"] - clip_start, "end": w["end"] - clip_start, "text": str(w["text"])}
        for w in words
        if w["end"] > clip_start and w["start"] < clip_end
    ]
    rel = [w for w in rel if w["end"] > 0 and w["start"] < clip_end - clip_start]
    lines: list[CaptionLine] = []
    bucket: list[dict] = []

    def flush() -> None:
        if not bucket:
            return
        lines.append(CaptionLine(
            start=max(bucket[0]["start"], 0.0),
            end=min(bucket[-1]["end"], clip_end - clip_start),
            words=list(bucket),
        ))
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


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


_TOKEN_CLEAN = re.compile(r"^\W+|\W+$")


def _norm(token: str) -> str:
    return _TOKEN_CLEAN.sub("", token).lower()


def _style_word(word_text: str, st: dict, is_active: bool, is_emphasis: bool) -> str:
    """Wrap one word with inline ASS overrides. Raw text escaped, tags added."""
    t = _esc(word_text)
    color = None
    if is_active and st["active"] != st["primary"]:
        color = st["active"]
    elif is_emphasis:
        color = st["emphasis"]
    if color:
        return "{\\c" + color + "&}" + t + "{\\c" + st["primary"] + "&}"
    return t


def _header(st: dict, width: int, height: int, margin_v: int) -> str:
    fmt_line = (
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
    )
    border_style = 3 if st.get("box") else 1
    secondary = st.get("secondary", "&H000000FF")
    style_line = (
        f"Style: Cap,{st['font']},{st['size']},{st['primary']},{secondary},{st['outline']},"
        f"&H80000000,{st['bold']},0,0,0,100,100,0,0,{border_style},{st['outline_w']},2,2,60,60,"
        f"{margin_v},1"
    )
    return f"""[Script Info]
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


def build_reveal_events(lines: list[CaptionLine], st: dict, emphasis: set[str]) -> list[str]:
    """One dialogue per word: cumulative text, active word highlighted."""
    events: list[str] = []
    for line in lines:
        tokens = [w["text"].strip() for w in line.words]
        emph_flags = [_norm(t) in emphasis for t in tokens]
        for i, w in enumerate(line.words):
            start = w["start"]
            end = line.words[i + 1]["start"] if i + 1 < len(line.words) else line.end
            if end <= start:
                end = start + 0.25
            parts = [
                _style_word(tokens[j], st, is_active=(j == i), is_emphasis=emph_flags[j])
                for j in range(i + 1)
            ]
            text = " ".join(parts)
            events.append(
                f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Cap,,0,0,0,,{text}"
            )
    return events


def build_karaoke_events(lines: list[CaptionLine], st: dict, emphasis: set[str]) -> list[str]:
    """Full line with \\k sweep; emphasized words pre-colored after their sweep."""
    events: list[str] = []
    for line in lines:
        parts = []
        for w in line.words:
            dur_cs = max(int((w["end"] - w["start"]) * 100), 1)
            token = _esc(w["text"].strip())
            if _norm(w["text"]) in emphasis:
                token = "{\\c" + st["emphasis"] + "&}" + token + "{\\c" + st["primary"] + "&}"
            parts.append("{\\k" + str(dur_cs) + "}" + token)
        text = " ".join(parts)
        events.append(
            f"Dialogue: 0,{_ass_time(line.start)},{_ass_time(max(line.end, line.start + 0.3))},"
            f"Cap,,0,0,0,,{text}"
        )
    return events


def build_static_events(lines: list[CaptionLine], st: dict, emphasis: set[str]) -> list[str]:
    """Legacy: one dialogue per line, emphasis words colored."""
    events: list[str] = []
    for line in lines:
        text = " ".join(
            _style_word(
                w["text"].strip(), st,
                is_active=False, is_emphasis=_norm(w["text"]) in emphasis,
            )
            for w in line.words
        )
        events.append(
            f"Dialogue: 0,{_ass_time(line.start)},{_ass_time(max(line.end, line.start + 0.3))},"
            f"Cap,,0,0,0,,{text}"
        )
    return events


_MODE_BUILDERS = {
    "reveal": build_reveal_events,
    "karaoke": build_karaoke_events,
    "static": build_static_events,
}


def build_ass(
    lines: list[CaptionLine],
    out_path: str | Path,
    width: int,
    height: int,
    style: str = "clean",
    margin_v_override: int | None = None,
    emphasis: list[str] | None = None,
) -> Path:
    st = STYLE_PACKS.get(style, STYLE_PACKS["clean"])
    margin_v = margin_v_override if margin_v_override is not None else st["margin_v"]
    emph = {_norm(e) for e in (emphasis or [])}

    builder = _MODE_BUILDERS.get(st["mode"], build_static_events)
    events = builder(lines, st, emph)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    content = _header(st, width, height, margin_v) + "\n".join(events) + "\n"
    out_path.write_text(content, encoding="utf-8")
    return out_path


def make_captions_for_clip(
    transcript_words: list[dict],
    abs_start: float,
    clip_start: float,
    clip_end: float,
    out_path: str | Path,
    width: int,
    height: int,
    style: str = "clean",
    margin_v_override: int | None = None,
    emphasis: list[str] | None = None,
) -> Path:
    """Convenience: absolute-time words -> styled .ass for one clip."""
    lines = group_words_into_lines(transcript_words, abs_start + clip_start, abs_start + clip_end)
    return build_ass(
        lines, out_path, width, height, style, margin_v_override, emphasis
    )
