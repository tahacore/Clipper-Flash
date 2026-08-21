import sqlite3
from pathlib import Path

from clipper_flash.state import (
    Clip,
    Stream,
    add_clip,
    clips_for_stream,
    connect,
    get_stream,
    list_streams,
    set_stream_status,
    update_clip,
    upsert_stream,
)


def make_conn(tmp_path: Path) -> sqlite3.Connection:
    return connect(tmp_path / "state.db")


def test_upsert_is_idempotent(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    s = Stream(video_id="abc123", url="https://youtu.be/abc123", title="Coding stream #1")
    assert upsert_stream(conn, s) is True  # inserted
    assert upsert_stream(conn, s) is False  # conflict -> updated, not inserted
    assert len(list_streams(conn)) == 1


def test_status_transitions_and_processed_at(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    s = Stream(video_id="v1", url="u", title="t")
    upsert_stream(conn, s)
    set_stream_status(conn, "v1", "transcribed")
    got = get_stream(conn, "v1")
    assert got and got.status == "transcribed" and got.processed_at is None

    set_stream_status(conn, "v1", "clipped", mark_processed=True)
    got = get_stream(conn, "v1")
    assert got and got.status == "clipped" and got.processed_at is not None


def test_invalid_status_raises(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    upsert_stream(conn, Stream(video_id="v2", url="u", title="t"))
    try:
        set_stream_status(conn, "v2", "bogus")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_clips_crud_and_ordering(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    upsert_stream(conn, Stream(video_id="v3", url="u", title="t"))
    later = Clip(stream_video_id="v3", start_sec=3600.0, end_sec=3660.0, title="second")
    earlier = Clip(stream_video_id="v3", start_sec=120.0, end_sec=180.0, title="first")
    id_later = add_clip(conn, later)
    add_clip(conn, earlier)

    rows = clips_for_stream(conn, "v3")
    assert [r["title"] for r in rows] == ["first", "second"]

    update_clip(conn, id_later, status="rendered", output_path="out/x.mp4")
    row = conn.execute("SELECT * FROM clips WHERE id=?", (id_later,)).fetchone()
    assert row["status"] == "rendered" and row["output_path"] == "out/x.mp4"
