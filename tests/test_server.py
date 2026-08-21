from fastapi.testclient import TestClient

from clipper_flash import server, state
from clipper_flash.state import Clip, Stream


def seed(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "DEFAULT_DB_DIR", tmp_path)
    conn = state.connect()
    state.upsert_stream(conn, Stream(video_id="v1", url="u", title="Coding stream"))
    state.upsert_stream(conn, Stream(video_id="v2", url="u", title="junk", status="skipped"))
    state.add_clip(
        conn,
        Clip(
            stream_video_id="v1",
            start_sec=0,
            end_sec=45,
            title="the funny part",
            layout="vertical-split",
            status="rendered",
            output_path="output/v1/01-funny.mp4",
        ),
    )
    return conn


def test_index_serves_gallery(tmp_path, monkeypatch) -> None:
    seed(tmp_path, monkeypatch)
    client = TestClient(server.app)
    res = client.get("/")
    assert res.status_code == 200
    assert "Clipper-Flash" in res.text


def test_api_clips_only_existing_files(tmp_path, monkeypatch) -> None:
    seed(tmp_path, monkeypatch)
    client = TestClient(server.app)
    clips = client.get("/api/clips").json()
    # output file doesn't exist on disk -> not listed
    assert clips == []


def test_api_clips_lists_with_poster(tmp_path, monkeypatch) -> None:
    seed(tmp_path, monkeypatch)
    real = tmp_path / "output" / "v1" / "01-funny.mp4"
    real.parent.mkdir(parents=True)
    real.write_bytes(b"x")
    poster = real.with_name("01-funny.poster.jpg")
    poster.write_bytes(b"jpgdata")

    conn = state.connect()
    conn.execute("UPDATE clips SET output_path=?", (str(real),))
    conn.commit()

    client = TestClient(server.app)
    clips = client.get("/api/clips").json()
    assert len(clips) == 1
    c = clips[0]
    assert c["title"] == "the funny part"
    assert c["duration_sec"] == 45.0
    assert c["poster"] and "/files/" in c["poster"]
    assert c["src"].startswith("/files/")


def test_api_status_includes_skipped(tmp_path, monkeypatch) -> None:
    seed(tmp_path, monkeypatch)
    client = TestClient(server.app)
    st = client.get("/api/status").json()
    assert {s["video_id"] for s in st} == {"v1", "v2"}


def test_files_endpoint_blocks_traversal(tmp_path, monkeypatch) -> None:
    seed(tmp_path, monkeypatch)
    client = TestClient(server.app)
    res = client.get("/files/..%2F..%2Fpyproject.toml")
    assert res.status_code in (403, 404)


def test_files_endpoint_404_for_missing(tmp_path, monkeypatch) -> None:
    seed(tmp_path, monkeypatch)
    client = TestClient(server.app)
    res = client.get("/files/nope.mp4")
    assert res.status_code == 404
