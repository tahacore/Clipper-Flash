"""Captions-first transcription: fetch YouTube caption tracks and clean them.

Strategy:
- Prefer manual (creator) subtitles, fall back to auto-generated captions.
- Prefer word-timed formats (json3) over plain vtt/srv.
- Clean artifacts: rolling-window duplication (vtt), boundary duplicates,
  then group words into readable segments for LLM analysis.

Everything here is offline-testable: parsing/grouping is pure, network is
isolated in fetch_transcript().
"""

from __future__ import annotations

import dataclasses
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# Segment grouping knobs
MAX_SEGMENT_WORDS = 14
MAX_SEGMENT_SECONDS = 6.0
SEGMENT_BREAK_GAP = 0.9


class CaptionsUnavailable(RuntimeError):
    """No usable caption track exists (or none in the requested language)."""


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Transcript:
    video_id: str
    url: str
    language: str
    source: str  # "manual" | "auto"
    duration_sec: float | None
    words: list[Word] = field(default_factory=list)

    @property
    def segments(self) -> list[dict]:
        return [dataclasses.asdict(s) for s in words_to_segments(self.words)]

    def to_dict(self) -> dict:
        return {
            "video_id": self.video_id,
            "url": self.url,
            "language": self.language,
            "source": self.source,
            "duration_sec": self.duration_sec,
            "word_count": len(self.words),
            "words": [dataclasses.asdict(w) for w in self.words],
            "segments": self.segments,
        }

    def save(self, path: str | Path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=1)


# --- track selection ---------------------------------------------------------


def pick_track(
    info: dict, lang: str = "en"
) -> tuple[str, str, str]:  # (kind, lang_key, url)
    """Choose the best caption track. Returns (manual|auto, language, url).

    Preference order: exact lang manual > exact lang auto > prefix match
    (e.g. 'en-US' for 'en') any manual > any auto.
    """
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}

    def best_url(tracks: dict, want: str) -> tuple[str | None, str]:
        # exact
        if want in tracks:
            return _fmt_url(tracks[want]), want
        # prefix (en -> en-US, en-GB ...)
        for key in tracks:
            if key.split("-")[0] == want.split("-")[0]:
                return _fmt_url(tracks[key]), key
        return None, ""

    for tracks, kind in ((manual, "manual"), (auto, "auto")):
        if not tracks:
            continue
        url, key = best_url(tracks, lang)
        if url:
            return kind, key, url

    # last resort: first available track of any kind/language
    for tracks, kind in ((manual, "manual"), (auto, "auto")):
        for key, variants in tracks.items():
            url = _fmt_url(variants)
            if url:
                return kind, key, url

    raise CaptionsUnavailable(
        "no caption track found - YouTube may still be generating captions, "
        "or the channel disabled them"
    )


def _fmt_url(variants: list[dict]) -> str | None:
    """Pick json3 > srv3 > vtt > srv1 > anything."""
    priority = ("json3", "srv3", "vtt", "srv1")
    by_ext = {v.get("ext"): v.get("url") for v in variants}
    for ext in priority:
        if by_ext.get(ext):
            return by_ext[ext]
    return variants[0].get("url") if variants else None


def download_track(url: str, timeout: float = 30.0) -> str:
    resp = httpx.get(
        url, timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    )
    resp.raise_for_status()
    return resp.text


# --- parsers -----------------------------------------------------------------


def parse_json3(text: str) -> list[Word]:
    """YouTube timedtext json3: events with word-level offsets."""
    data = json.loads(text)
    words: list[Word] = []
    for ev in data.get("events") or []:
        segs = ev.get("segs")
        if not segs:
            continue
        base_ms = ev.get("tStartMs", 0)
        dur_ms = ev.get("dDurationMs", 0)
        # collect raw tokens first so we can compute ends from successors
        tokens: list[tuple[float, str]] = []
        for seg in segs:
            txt = (seg.get("utf8") or "").replace("\n", " ")
            if not txt.strip():
                continue
            off_ms = seg.get("tOffsetMs")
            start_s = (base_ms + (off_ms if off_ms is not None else 0)) / 1000.0
            tokens.append((start_s, txt))
        for i, (start_s, txt) in enumerate(tokens):
            end_s = tokens[i + 1][0] if i + 1 < len(tokens) else (base_ms + dur_ms) / 1000.0
            if end_s <= start_s:
                end_s = start_s + 0.01
            words.append(Word(start=round(start_s, 3), end=round(end_s, 3), text=txt))
    return dedup_words(words)


_VTT_TS_RE = re.compile(r"<(\d{2}:\d{2}:\d{2}\.\d{3})>")
_VTT_CUE_TIME_RE = re.compile(
    r"^(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})\.(\d{3})"
)


def _vtt_ts(h: int, m: int, s: int, ms: int) -> float:
    return h * 3600 + m * 60 + s + ms / 1000


def parse_vtt(text: str) -> list[Word]:
    """Plain vtt parser with auto-caption rolling-window handling.

    Auto captions repeat the previous cue's tail on every new cue; keeping the
    final line of each cue and dropping exact repeats yields a clean stream.
    Word timing is approximated by distributing cue duration across words.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    words: list[Word] = []
    prev_last_line: str | None = None
    i = 0
    while i < len(lines):
        m = _VTT_CUE_TIME_RE.match(lines[i].strip())
        if not m:
            i += 1
            continue
        start = _vtt_ts(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))
        end = _vtt_ts(int(m.group(5)), int(m.group(6)), int(m.group(7)), int(m.group(8)))
        # gather cue body until blank line
        body: list[str] = []
        i += 1
        while i < len(lines) and lines[i].strip():
            body.append(lines[i])
            i += 1
        if not body:
            continue
        # drop inline timestamps / speaker tags, keep final line (rolling fix)
        cleaned_body = [_VTT_TS_RE.sub("", re.sub(r"</?c[^>]*>", "", ln)).strip() for ln in body]
        keep = cleaned_body[-1] if len(cleaned_body) > 1 else cleaned_body[0]
        if prev_last_line is not None and keep == prev_last_line:
            continue
        prev_last_line = keep
        for w_start, w_end, token in _spread_words(keep, start, end):
            words.append(Word(start=w_start, end=w_end, text=token))
    return dedup_words(words)


def _spread_words(line: str, start: float, end: float):
    tokens = line.split()
    if not tokens:
        return []
    weights = [max(len(t), 1) for t in tokens]
    total = sum(weights)
    dur = max(end - start, 0.2)
    out = []
    cursor = start
    for tok, w in zip(tokens, weights, strict=True):
        span = dur * w / total
        out.append((round(cursor, 3), round(cursor + span, 3), tok))
        cursor += span
    return out


# --- cleaning & grouping -----------------------------------------------------


@dataclass
class Segment:
    start: float
    end: float
    text: str


_FILLER = {"[Music]", "[Applause]", "[Laughter]", "[Music] ", "[Applause] ", "[Laughter] "}


def dedup_words(words: list[Word]) -> list[Word]:
    """Drop filler tags and immediate duplicate tokens (caption artifacts)."""
    out: list[Word] = []
    for w in words:
        t = w.text.strip()
        if not t or t in _FILLER:
            continue
        if out:
            prev = out[-1]
            if t.lower() == prev.text.lower() and abs(w.start - prev.start) < 0.05:
                continue
        out.append(Word(start=w.start, end=max(w.end, w.start + 0.01), text=t))
    return out


def words_to_segments(words: list[Word]) -> list[Segment]:
    """Group words into LLM-friendly segments (sentence-ish chunks)."""
    segments: list[Segment] = []
    current: list[Word] = []

    def flush() -> None:
        if not current:
            return
        text = " ".join(w.text for w in current).strip()
        if text:
            segments.append(Segment(start=current[0].start, end=current[-1].end, text=text))
        current.clear()

    for w in words:
        if current:
            gap = w.start - current[-1].end
            span = w.end - current[0].start
            too_long = span > MAX_SEGMENT_SECONDS or len(current) >= MAX_SEGMENT_WORDS
            if gap > SEGMENT_BREAK_GAP or too_long:
                flush()
        current.append(w)
    flush()
    return segments


# --- high-level entry --------------------------------------------------------


def fetch_transcript(url_or_id: str, lang: str = "en", probe=None) -> Transcript:
    """Fetch and clean a transcript for a video. Raises CaptionsUnavailable."""
    from clipper_flash import youtube

    vid = youtube.extract_video_id(url_or_id) or url_or_id
    url = youtube.WATCH_URL.format(video_id=vid)
    info = (probe or youtube.probe_video)(url)

    kind, lang_key, track_url = pick_track(info, lang)
    raw = download_track(track_url)

    if "fmt=json3" in track_url:
        words = parse_json3(raw)
    elif "fmt=srv3" in track_url:
        words = parse_vtt(_srv3_to_vtt(raw))
    else:
        words = parse_vtt(raw)

    if not words:
        raise CaptionsUnavailable(
            f"caption track downloaded but parsed empty ({lang_key})"
        )

    return Transcript(
        video_id=vid,
        url=url,
        language=lang_key,
        source=kind,
        duration_sec=info.get("duration"),
        words=words,
    )


def _srv3_to_vtt(xml_text: str) -> str:
    """Convert YouTube srv3 XML into pseudo-vtt cues (keeps word timing)."""
    import html as _html

    out_lines: list[str] = ["WEBVTT", ""]
    cue_re = re.compile(r'<text start="([\d.]+)" dur="([\d.]+)"[^>]*>(.*?)</text>', re.S)
    for m in cue_re.finditer(xml_text):
        start, dur, body = float(m.group(1)), float(m.group(2)), m.group(3)
        body = _html.unescape(re.sub(r"<[^>]+>", " ", body)).strip()
        if not body:
            continue
        h, rem = divmod(start, 3600)
        mn, sec = divmod(rem, 60)
        e = start + dur
        eh, erem = divmod(e, 3600)
        emn, esec = divmod(erem, 60)
        stamp = f"{int(h):02d}:{int(mn):02d}:{sec:06.3f}"
        stamp_end = f"{int(eh):02d}:{int(emn):02d}:{esec:06.3f}"
        out_lines.append(f"{stamp} --> {stamp_end}")
        out_lines.append(body)
        out_lines.append("")
    return "\n".join(out_lines)
