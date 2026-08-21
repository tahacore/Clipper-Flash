import json
import subprocess
from pathlib import Path

import pytest

from clipper_flash import render


def fake_probe(path):
    return {"width": 1920, "height": 1080, "duration": 120.0, "fps": 30.0}


def test_render_clip_builds_expected_ffmpeg_call(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "probe", fake_probe)
    captured = {}

    def fake_run(cmd, **kwargs):
        # render + poster both invoke ffmpeg; keep them distinguishable
        if "libx264" in cmd:
            captured["cmd"] = cmd
            out = Path(cmd[-1])
            out.write_bytes(b"fake")  # pretend success
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(render.subprocess, "run", fake_run)

    spec_clip = {
        "input": str(tmp_path / "in.mp4"),
        "out": str(tmp_path / "out" / "clip.mp4"),
        "layout": "vertical-split",
        "start": 5.0,
        "end": 35.0,
    }
    (tmp_path / "in.mp4").write_bytes(b"fake")
    result = render.render_clip(spec_clip, workdir=tmp_path)

    cmd = captured["cmd"]
    assert "-ss" in cmd and "5.000" in cmd
    assert "-to" in cmd and "35.000" in cmd
    assert "libx264" in cmd and "+faststart" in cmd
    # polish defaults on: loudness normalization + fades
    assert any("loudnorm" in str(a) for a in cmd)
    assert any("fade=t=out" in str(a) for a in cmd)
    assert result.width == 1080 and result.height == 1920
    assert result.duration_sec == 30.0
    assert result.captions is False


def test_render_clip_with_captions_generates_ass(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "probe", fake_probe)
    monkeypatch.setattr(
        render.subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""),
    )
    words = [
        {"start": 10.0 + i * 0.5, "end": 10.4 + i * 0.5, "text": f"w{i}"} for i in range(10)
    ]
    tpath = tmp_path / "t.json"
    tpath.write_text(json.dumps({"words": words}), encoding="utf-8")

    spec_clip = {
        "input": str(tmp_path / "in.mp4"),
        "out": str(tmp_path / "clip.mp4"),
        "layout": "passthrough",
        "start": 0.0,
        "end": 10.0,
        "captions": True,
        "transcript": str(tpath),
        "abs_start": 10.0,
    }
    (tmp_path / "in.mp4").write_bytes(b"x")
    result = render.render_clip(spec_clip, workdir=tmp_path)
    ass_file = Path(spec_clip["out"]).with_suffix(".ass")
    assert result.captions is True
    content = ass_file.read_text(encoding="utf-8")
    assert "Dialogue: 0,0:00:00.00" in content
    assert "w0 w1 w2" in content


def make_words(n):
    return [
        {"start": float(i) * 0.5, "end": float(i) * 0.5 + 0.4, "text": f"w{i}"}
        for i in range(n)
    ]


def test_vertical_split_captions_auto_sit_above_strip(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "probe", fake_probe)
    monkeypatch.setattr(
        render.subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""),
    )
    tpath = tmp_path / "t.json"
    tpath.write_text(json.dumps({"words": make_words(6)}), encoding="utf-8")
    (tmp_path / "in.mp4").write_bytes(b"x")

    spec_clip = {
        "input": str(tmp_path / "in.mp4"),
        "out": str(tmp_path / "clip.mp4"),
        "layout": "vertical-split",
        "start": 0.0,
        "end": 5.0,
        "captions": True,
        "transcript": str(tpath),
        "abs_start": 0.0,
    }
    render.render_clip(spec_clip, workdir=tmp_path)
    style_line = Path(spec_clip["out"]).with_suffix(".ass").read_text(encoding="utf-8")
    # default strip 640 -> MarginV 664 (just above the cam strip)
    assert ",664,1" in style_line


def test_caption_margin_v_override_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "probe", fake_probe)
    monkeypatch.setattr(
        render.subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""),
    )
    tpath = tmp_path / "t.json"
    tpath.write_text(json.dumps({"words": make_words(6)}), encoding="utf-8")
    (tmp_path / "in.mp4").write_bytes(b"x")

    spec_clip = {
        "input": str(tmp_path / "in.mp4"),
        "out": str(tmp_path / "clip.mp4"),
        "layout": "vertical-split",
        "start": 0.0,
        "end": 5.0,
        "captions": True,
        "transcript": str(tpath),
        "abs_start": 0.0,
        "caption_margin_v": 700,
    }
    render.render_clip(spec_clip, workdir=tmp_path)
    style_line = Path(spec_clip["out"]).with_suffix(".ass").read_text(encoding="utf-8")
    assert ",700,1" in style_line


def test_render_rejects_unknown_layout(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "probe", fake_probe)
    (tmp_path / "in.mp4").write_bytes(b"x")
    with pytest.raises(render.RenderError, match="unknown layout"):
        render.render_clip(
            {
                "input": str(tmp_path / "in.mp4"),
                "out": str(tmp_path / "o.mp4"),
                "layout": "diagonal",
            },
            workdir=tmp_path,
        )


def test_render_rejects_missing_input(tmp_path):
    with pytest.raises(render.RenderError, match="input missing"):
        render.render_clip({"input": str(tmp_path / "nope.mp4"), "out": "o.mp4"}, workdir=tmp_path)


def test_render_spec_collects_partial_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "probe", fake_probe)
    monkeypatch.setattr(
        render.subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""),
    )
    good = tmp_path / "good.mp4"
    good.write_bytes(b"x")
    spec = {
        "clips": [
            {"input": str(tmp_path / "missing.mp4"), "out": str(tmp_path / "a.mp4")},
            {"input": str(good), "out": str(tmp_path / "b.mp4"), "start": 0, "end": 10},
        ]
    }
    results = render.render_spec_from_dict(spec)
    assert len(results) == 1
