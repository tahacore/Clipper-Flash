"""Minimal gallery UI over the state DB and output folder.

`cf serve` -> http://localhost:8600 shows tracked streams, their clips, and
inline video previews. Read-only by design; the pipeline stays CLI-driven.
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


@app.get("/api/streams")
def api_streams() -> list[dict]:
    conn = state.connect()
    out = []
    for s in state.list_streams(conn):
        d = {
            "video_id": s.video_id,
            "title": s.title,
            "status": s.status,
            "first_seen_at": s.first_seen_at,
            "url": s.url,
            "clips": [],
        }
        for c in state.clips_for_stream(conn, s.video_id):
            clip = dict(c)
            if clip.get("output_path") and Path(clip["output_path"]).exists():
                clip["playable"] = True
            else:
                clip["playable"] = False
            d["clips"].append(clip)
        out.append(d)
    return out


@app.get("/files/{file_path:path}")
def files(file_path: str) -> FileResponse:
    """Serve rendered clips. Only paths under ./output are allowed."""
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
