from fastapi.testclient import TestClient

from clipper_flash import server, state
from clipper_flash.state import Clip, Stream


def seed(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "DEFAULT_DB_DIR", tmp_path)
    conn = state.connect()
    state.upsert_stream(conn, Stream(video_id="v1", url="u", title="Coding stream"))
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


def test_api_streams_shape_and_playability(tmp_path, monkeypatch) -> None:
    seed(tmp_path, monkeypatch)
    client = TestClient(server.app)
    data = client.get("/api/streams").json()
    assert len(data) == 1
    s = data[0]
    assert s["video_id"] == "v1"
    assert s["status"] == "new"
    assert s["clips"][0]["playable"] is False  # output file doesn't exist yet
    assert s["clips"][0]["layout"] == "vertical-split"


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
