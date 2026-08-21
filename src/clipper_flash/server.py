"""Minimal gallery UI over the state DB and output folder.

`cf serve` -> http://localhost:8600 shows a clip-first gallery: rendered
clips with poster thumbnails front and center; pipeline status demoted to a
collapsed strip. Read-only by design; the pipeline stays CLI-driven.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from clipper_flash import state

app = FastAPI(title="Clipper-Flash", version="0.1.0")

_GALLERY = Path(__file__).parent / "static" / "gallery.html"


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _GALLERY.read_text(encoding="utf-8")


@app.get("/api/clips")
def api_clips() -> list[dict]:
    """All rendered clips that exist on disk, newest first."""
    conn = state.connect()
    out = []
    for s in state.list_streams(conn):
        for c in state.clips_for_stream(conn, s.video_id):
            clip = dict(c)
            path = clip.get("output_path")
            if not path or not Path(path).exists():
                continue
            poster = Path(path).with_name(Path(path).stem + ".poster.jpg")
            out.append({
                "title": clip.get("title") or Path(path).stem,
                "video_id": s.video_id,
                "stream_title": s.title,
                "layout": clip["layout"],
                "duration_sec": round(clip["end_sec"] - clip["start_sec"], 1),
                "created_at": clip["created_at"],
                "src": "/files/" + str(Path(path).as_posix()),
                "poster": (
                    "/files/" + str(poster.as_posix()) if poster.exists() else None
                ),
            })
    return sorted(out, key=lambda c: c["created_at"], reverse=True)


@app.get("/api/status")
def api_status() -> list[dict]:
    """Pipeline status (demoted view): tracked streams and their stage."""
    conn = state.connect()
    return [
        {
            "video_id": s.video_id,
            "title": s.title,
            "status": s.status,
            "first_seen_at": s.first_seen_at,
        }
        for s in state.list_streams(conn)
    ]


@app.get("/files/{file_path:path}")
def files(file_path: str) -> FileResponse:
    """Serve rendered clips/posters. Only paths under ./output are allowed."""
    root = Path("output").resolve()
    target = (root / file_path).resolve()
    if not str(target).startswith(str(root)):
        raise HTTPException(status_code=403, detail="forbidden")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(target)


def main() -> None:  # pragma: no cover - manual entry
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8600)


if __name__ == "__main__":
    main()
