"""SQLite-backed state: which streams were seen/processed, and their clips.

Design goals:
- Idempotency: re-running any command never duplicates work.
- Portability: single file DB, stdlib only, WAL mode.
- Debuggability: timestamps stored as ISO-8601 UTC strings.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_DB_DIR = Path.home() / ".clipper-flash"
SCHEMA_VERSION = 1

# Stream lifecycle:
#   new -> captions_pending -> transcribed -> clipped | failed | skipped
STREAM_STATUSES = ("new", "captions_pending", "transcribed", "clipped", "failed", "skipped")
# Clip lifecycle: planned -> rendered | failed
CLIP_STATUSES = ("planned", "rendered", "failed")


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Stream:
    video_id: str
    url: str
    title: str
    channel_id: str = ""
    status: str = "new"
    duration_sec: float | None = None
    is_live_content: bool = False
    first_seen_at: str = field(default_factory=utcnow)
    updated_at: str = field(default_factory=utcnow)
    processed_at: str | None = None
    error: str | None = None


@dataclass
class Clip:
    stream_video_id: str
    start_sec: float
    end_sec: float
    title: str = ""
    layout: str = "vertical-split"
    status: str = "planned"
    output_path: str | None = None
    spec_json: str | None = None
    created_at: str = field(default_factory=utcnow)


def db_path(default_dir: Path | None = None) -> Path:
    base = Path(default_dir) if default_dir else DEFAULT_DB_DIR
    base.mkdir(parents=True, exist_ok=True)
    return base / "state.db"


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS streams (
            video_id TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            title TEXT NOT NULL,
            channel_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'new',
            duration_sec REAL,
            is_live_content INTEGER NOT NULL DEFAULT 0,
            first_seen_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            processed_at TEXT,
            error TEXT
        );
        CREATE TABLE IF NOT EXISTS clips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stream_video_id TEXT NOT NULL REFERENCES streams(video_id),
            start_sec REAL NOT NULL,
            end_sec REAL NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            layout TEXT NOT NULL DEFAULT 'vertical-split',
            status TEXT NOT NULL DEFAULT 'planned',
            output_path TEXT,
            spec_json TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_clips_stream ON clips(stream_video_id);
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT NOT NULL DEFAULT '',
            video_id TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL,              -- stream_summary | clip_note | note
            text TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_memories_channel ON memories(channel_id);
        """
    )
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),)
        )
    conn.commit()


# --- streams -----------------------------------------------------------------


def upsert_stream(conn: sqlite3.Connection, stream: Stream) -> bool:
    """Insert stream if unknown, refresh title/duration if known.

    Returns True if newly inserted, False if an existing record was updated.
    """
    exists = conn.execute(
        "SELECT 1 FROM streams WHERE video_id=?", (stream.video_id,)
    ).fetchone()
    if exists:
        conn.execute(
            """
            UPDATE streams
            SET title=?, duration_sec=COALESCE(?, duration_sec), updated_at=?
            WHERE video_id=?
            """,
            (stream.title, stream.duration_sec, utcnow(), stream.video_id),
        )
        conn.commit()
        return False
    conn.execute(
        """
        INSERT INTO streams (video_id, url, title, channel_id, status, duration_sec,
                             is_live_content, first_seen_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            stream.video_id,
            stream.url,
            stream.title,
            stream.channel_id,
            stream.status,
            stream.duration_sec,
            int(stream.is_live_content),
            stream.first_seen_at,
            utcnow(),
        ),
    )
    conn.commit()
    return True


def get_stream(conn: sqlite3.Connection, video_id: str) -> Stream | None:
    row = conn.execute("SELECT * FROM streams WHERE video_id=?", (video_id,)).fetchone()
    return _row_to_stream(row) if row else None


def list_streams(conn: sqlite3.Connection, status: str | None = None) -> list[Stream]:
    if status:
        rows = conn.execute(
            "SELECT * FROM streams WHERE status=? ORDER BY first_seen_at DESC", (status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM streams ORDER BY first_seen_at DESC").fetchall()
    return [_row_to_stream(r) for r in rows]


def set_stream_status(
    conn: sqlite3.Connection,
    video_id: str,
    status: str,
    error: str | None = None,
    mark_processed: bool = False,
) -> None:
    if status not in STREAM_STATUSES:
        raise ValueError(f"unknown stream status: {status}")
    processed_at = utcnow() if mark_processed else None
    conn.execute(
        """
        UPDATE streams
        SET status=?, error=COALESCE(?, error), processed_at=COALESCE(?, processed_at),
            updated_at=?
        WHERE video_id=?
        """,
        (status, error, processed_at, utcnow(), video_id),
    )
    conn.commit()


def _row_to_stream(row: sqlite3.Row) -> Stream:
    return Stream(
        video_id=row["video_id"],
        url=row["url"],
        title=row["title"],
        channel_id=row["channel_id"],
        status=row["status"],
        duration_sec=row["duration_sec"],
        is_live_content=bool(row["is_live_content"]),
        first_seen_at=row["first_seen_at"],
        updated_at=row["updated_at"],
        processed_at=row["processed_at"],
        error=row["error"],
    )


# --- clips -------------------------------------------------------------------


def add_clip(conn: sqlite3.Connection, clip: Clip) -> int:
    cur = conn.execute(
        """
        INSERT INTO clips (stream_video_id, start_sec, end_sec, title, layout, status,
                           output_path, spec_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            clip.stream_video_id,
            clip.start_sec,
            clip.end_sec,
            clip.title,
            clip.layout,
            clip.status,
            clip.output_path,
            clip.spec_json,
            clip.created_at,
        ),
    )
    conn.commit()
    assert cur.lastrowid is not None
    return cur.lastrowid


def update_clip(
    conn: sqlite3.Connection,
    clip_id: int,
    status: str | None = None,
    output_path: str | None = None,
    spec: dict | None = None,
) -> None:
    if status and status not in CLIP_STATUSES:
        raise ValueError(f"unknown clip status: {status}")
    conn.execute(
        """
        UPDATE clips
        SET status=COALESCE(?, status),
            output_path=COALESCE(?, output_path),
            spec_json=COALESCE(?, spec_json)
        WHERE id=?
        """,
        (status, output_path, json.dumps(spec) if spec else None, clip_id),
    )
    conn.commit()


def clips_for_stream(conn: sqlite3.Connection, video_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM clips WHERE stream_video_id=? ORDER BY start_sec", (video_id,)
    ).fetchall()


def stream_summary(conn: sqlite3.Connection, stream: Stream) -> dict:
    clips = [dict(c) for c in clips_for_stream(conn, stream.video_id)]
    d = asdict(stream)
    d["clips"] = clips
    return d


# --- memory ------------------------------------------------------------------

MEMORY_KINDS = ("stream_summary", "clip_note", "note")


def add_memory(
    conn: sqlite3.Connection,
    kind: str,
    text: str,
    channel_id: str = "",
    video_id: str = "",
) -> int:
    if kind not in MEMORY_KINDS:
        raise ValueError(f"unknown memory kind: {kind} (use {MEMORY_KINDS})")
    text = text.strip()
    if not text:
        raise ValueError("memory text must not be empty")
    cur = conn.execute(
        "INSERT INTO memories (channel_id, video_id, kind, text, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (channel_id, video_id, kind, text, utcnow()),
    )
    conn.commit()
    assert cur.lastrowid is not None
    return cur.lastrowid


def list_memories(
    conn: sqlite3.Connection,
    channel_id: str | None = None,
    kind: str | None = None,
    limit: int = 200,
) -> list[sqlite3.Row]:
    q = "SELECT * FROM memories WHERE 1=1"
    args: list = []
    if channel_id:
        q += " AND channel_id=?"
        args.append(channel_id)
    if kind:
        q += " AND kind=?"
        args.append(kind)
    q += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    return conn.execute(q, args).fetchall()


def delete_memory(conn: sqlite3.Connection, memory_id: int) -> None:
    conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))
    conn.commit()
