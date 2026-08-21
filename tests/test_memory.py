import json

import pytest

from clipper_flash import state
from clipper_flash.state import Clip, Stream, add_clip, add_memory, delete_memory, list_memories


def test_memory_crud(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(state, "DEFAULT_DB_DIR", tmp_path)
    conn = state.connect()
    i1 = add_memory(
        conn, "stream_summary", "Told the Thailand cleaning-lady story at 52:28", video_id="v1"
    )
    i2 = add_memory(conn, "clip_note", "Title used curiosity gap; performed well", channel_id="UCx")
    i3 = add_memory(conn, "note", "She prefers hype caption style")
    rows = list_memories(conn)
    assert {r["id"] for r in rows} == {i1, i2, i3}
    assert rows[0]["id"] >= rows[-1]["id"]  # newest first

    only_v1 = list_memories(conn, kind="stream_summary")
    assert [r["id"] for r in only_v1] == [i1]

    delete_memory(conn, i2)
    assert {r["id"] for r in list_memories(conn)} == {i1, i3}


def test_memory_rejects_bad_kind_and_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(state, "DEFAULT_DB_DIR", tmp_path)
    conn = state.connect()
    with pytest.raises(ValueError):
        add_memory(conn, "bogus_kind", "x")
    with pytest.raises(ValueError):
        add_memory(conn, "note", "   ")


def test_clear_skipped_streams(tmp_path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from clipper_flash.cli import app

    monkeypatch.setattr(state, "DEFAULT_DB_DIR", tmp_path)
    conn = state.connect()
    state.upsert_stream(conn, Stream(video_id="keep1", url="u", title="real", status="new"))
    state.upsert_stream(conn, Stream(video_id="skip1", url="u", title="junk", status="skipped"))
    add_clip(conn, Clip(stream_video_id="skip1", start_sec=0, end_sec=10))

    runner = CliRunner()
    res = runner.invoke(app, ["clear", "--skipped", "--yes", "--json"])
    assert res.exit_code == 0, res.output
    assert json.loads(res.output) == {"removed_streams": 1, "removed_clips": 1}
    assert state.get_stream(conn, "keep1") is not None
    assert state.get_stream(conn, "skip1") is None


def test_clear_all_requires_flag(tmp_path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from clipper_flash.cli import app

    monkeypatch.setattr(state, "DEFAULT_DB_DIR", tmp_path)
    runner = CliRunner()
    res = runner.invoke(app, ["clear", "--yes", "--json"])
    assert res.exit_code != 0
