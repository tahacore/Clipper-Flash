from clipper_flash.subtitles import (
    STYLE_PACKS,
    build_ass,
    group_words_into_lines,
    make_captions_for_clip,
)

WORDS = [
    {"start": 10.0 + i * 0.5, "end": 10.4 + i * 0.5, "text": t}
    for i, t in enumerate(["this", "was", "never", "about", "money"])
]


def test_reveal_events_one_per_word(tmp_path) -> None:
    lines = group_words_into_lines(WORDS, 10.0, 13.0)
    out = build_ass(lines, tmp_path / "a.ass", 1080, 1920, style="hype")
    content = out.read_text(encoding="utf-8")
    dialogues = [ln for ln in content.splitlines() if ln.startswith("Dialogue")]
    assert len(dialogues) == 5  # one event per word


def _dialogues(path) -> list[str]:
    return [
        ln for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.startswith("Dialogue")
    ]


def test_reveal_active_word_highlighted(tmp_path) -> None:
    lines = group_words_into_lines(WORDS, 10.0, 13.0)
    out = build_ass(lines, tmp_path / "a.ass", 1080, 1920, style="hype")
    dialogues = _dialogues(out)
    # event 3 ("this was never") must highlight "never" with the active color
    assert "{\\c&H0000FFFF&}never{\\c" in dialogues[2]
    # and earlier words must NOT be highlighted in that event
    assert "{\\c&H0000FFFF&}this" not in dialogues[2]


def test_emphasis_words_permanently_colored(tmp_path) -> None:
    lines = group_words_into_lines(WORDS, 10.0, 13.0)
    out = build_ass(lines, tmp_path / "a.ass", 1080, 1920, style="hype", emphasis=["money"])
    # "money" appears only in the last event, colored with emphasis color
    last = _dialogues(out)[-1]
    assert "{\\c&H0000D7FF&}money" in last
    # emphasis survives even when the word is also the active word
    lines2 = group_words_into_lines(WORDS[:1], 10.0, 11.0)
    out2 = build_ass(lines2, tmp_path / "b.ass", 1080, 1920, style="hype", emphasis=["this"])
    first = _dialogues(out2)[0]
    assert "{\\c&H0000D7FF&}this" in first  # emphasis wins over active


def test_karaoke_mode_uses_k_tags(tmp_path) -> None:
    lines = group_words_into_lines(WORDS, 10.0, 13.0)
    out = build_ass(lines, tmp_path / "a.ass", 1080, 1920, style="karaoke-fill")
    dialogues = _dialogues(out)
    assert len(dialogues) == len(lines)  # one per line, not per word
    assert "{\\k" in dialogues[0]


def test_static_minimal_mode(tmp_path) -> None:
    lines = group_words_into_lines(WORDS, 10.0, 13.0)
    out = build_ass(lines, tmp_path / "a.ass", 1080, 1920, style="minimal")
    assert len(_dialogues(out)) == len(lines)


def test_legacy_bold_style_still_works(tmp_path) -> None:
    assert "bold" in STYLE_PACKS
    lines = group_words_into_lines(WORDS, 10.0, 13.0)
    out = build_ass(lines, tmp_path / "a.ass", 1080, 1920, style="bold")
    assert "Dialogue" in out.read_text(encoding="utf-8")


def test_make_captions_for_clip_end_to_end(tmp_path) -> None:
    p = make_captions_for_clip(
        WORDS, abs_start=10.0, clip_start=0.0, clip_end=3.0,
        out_path=tmp_path / "c.ass", width=1080, height=1920,
        style="hype", margin_v_override=664, emphasis=["never"],
    )
    content = p.read_text(encoding="utf-8")
    assert ",664,1" in content  # margin override applied
    assert "{\\c&H0000D7FF&}never" in content
