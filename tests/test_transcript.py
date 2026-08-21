import json

import pytest

from clipper_flash.transcript import (
    CaptionsUnavailable,
    Transcript,
    Word,
    dedup_words,
    parse_json3,
    parse_vtt,
    pick_track,
    words_to_segments,
)

JSON3 = """
{
  "events": [
    {"tStartMs": 0, "dDurationMs": 1200, "segs": [
      {"utf8": "hello", "tOffsetMs": 0},
      {"utf8": " world", "tOffsetMs": 400}
    ]},
    {"tStartMs": 1500, "dDurationMs": 800, "segs": [{"utf8": "welcome", "tOffsetMs": 0}]},
    {"tStartMs": 2400, "dDurationMs": 600, "segs": [{"utf8": "back", "tOffsetMs": 0}]},
    {"tStartMs": 3000, "dDurationMs": 500, "segs": [{"utf8": "[Music]", "tOffsetMs": 0}]},
    {"tStartMs": 3600, "dDurationMs": 900, "segs": []}
  ]
}
"""

VTT_ROLLING = """WEBVTT

00:00:00.000 --> 00:00:02.000
hey everyone

00:00:01.500 --> 00:00:03.500
hey everyone
today we are

00:00:03.000 --> 00:00:05.000
today we are
building a clipper
"""


def test_parse_json3_word_timings() -> None:
    words = parse_json3(JSON3)
    assert [w.text for w in words] == ["hello", "world", "welcome", "back"]
    assert words[0].start == 0.0
    assert words[1].start == pytest.approx(0.4)
    assert words[2].end == pytest.approx(2.3)


def test_json3_drops_filler_events() -> None:
    words = parse_json3(JSON3)
    assert all("[Music]" not in w.text for w in words)


def test_vtt_rolling_window_dedup() -> None:
    words = parse_vtt(VTT_ROLLING)
    text = " ".join(w.text for w in words)
    # each phrase appears exactly once despite rolling repeats
    assert text.count("hey everyone") == 1
    assert text.count("today we are") == 1
    assert text.count("building a clipper") == 1


def test_segments_grouping_on_gap() -> None:
    words = [
        Word(0.0, 0.5, "one"),
        Word(0.6, 1.0, "two"),
        Word(5.0, 5.5, "three"),  # big gap -> new segment
    ]
    segs = words_to_segments(words)
    assert len(segs) == 2
    assert segs[0].text == "one two"
    assert segs[1].text == "three"


def test_segments_max_words() -> None:
    words = [Word(float(i), float(i) + 0.4, f"w{i}") for i in range(40)]
    segs = words_to_segments(words)
    assert max(len(s.text.split()) for s in segs) <= 14


def test_dedup_immediate_duplicates() -> None:
    words = [Word(1.0, 1.2, "yeah"), Word(1.0, 1.2, "Yeah"), Word(1.5, 1.8, "cool")]
    out = dedup_words(words)
    assert [w.text for w in out] == ["yeah", "cool"]


def test_pick_track_prefers_manual_exact_lang() -> None:
    info = {
        "subtitles": {
            "en": [{"ext": "vtt", "url": "manual-en"}],
            "fr": [{"ext": "vtt", "url": "manual-fr"}],
        },
        "automatic_captions": {"en": [{"ext": "json3", "url": "auto-en"}]},
    }
    kind, lang, url = pick_track(info, "en")
    assert (kind, lang, url) == ("manual", "en", "manual-en")


def test_pick_track_prefix_match_and_format_priority() -> None:
    info = {
        "subtitles": {},
        "automatic_captions": {
            "en-US": [{"ext": "vtt", "url": "u-vtt"}, {"ext": "json3", "url": "u-json3"}]
        },
    }
    kind, lang, url = pick_track(info, "en")
    assert (kind, lang, url) == ("auto", "en-US", "u-json3")


def test_pick_track_raises_when_empty() -> None:
    with pytest.raises(CaptionsUnavailable):
        pick_track({"subtitles": {}, "automatic_captions": {}})


def test_transcript_roundtrip(tmp_path) -> None:
    t = Transcript(
        video_id="abc", url="u", language="en", source="auto",
        duration_sec=100.0, words=[Word(0, 1, "hi"), Word(1.2, 2, "there")],
    )
    p = tmp_path / "t.json"
    t.save(p)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["word_count"] == 2
    assert data["segments"][0]["text"] == "hi there"
