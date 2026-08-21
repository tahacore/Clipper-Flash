"""Detect new (unprocessed) uploads for a channel and record them in state.

Default policy: only former livestreams (yt-dlp live_broadcast_content ==
"was_live") are considered clip-worthy. Pass include_all=True to treat any
upload as a candidate.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from clipper_flash import state, youtube
from clipper_flash.state import Stream


@dataclass
class DetectReport:
    channel_id: str
    scanned: int
    new_streams: list[Stream]
    known: int
    skipped_non_live: int
    failed_probes: list[dict] | None = None

    def __post_init__(self) -> None:
        if self.failed_probes is None:
            self.failed_probes = []


def detect_new_streams(
    conn: sqlite3.Connection,
    channel_ref: str,
    include_all: bool = False,
    lookback: int = 15,
    prober=None,
    rss_fetcher=None,
    rss_parser=None,
) -> DetectReport:
    """Scan a channel's recent uploads; upsert unseen ones into state.

    Injectable args make this testable without network access.
    """
    prober = prober or youtube.probe_video
    rss_fetcher = rss_fetcher or youtube.fetch_rss_xml
    rss_parser = rss_parser or youtube.parse_rss

    channel_id = youtube.resolve_channel_id(channel_ref)
    entries = rss_parser(rss_fetcher(channel_id))[:lookback]

    new_streams: list[Stream] = []
    known = 0
    skipped_non_live = 0
    failed_probes: list[dict] = []

    for entry in entries:
        existing = state.get_stream(conn, entry.video_id)
        if existing:
            known += 1
            continue

        try:
            info = prober(entry.url)
        except Exception as exc:  # noqa: BLE001 - one bad video must not kill the scan
            failed_probes.append({"video_id": entry.video_id, "error": str(exc)[:300]})
            continue

        was_live = info.get("live_broadcast_content") == "was_live"
        if not was_live and not include_all:
            skipped_non_live += 1
            # Record as skipped so we never probe it again.
            stream = Stream(
                video_id=entry.video_id,
                url=entry.url,
                title=entry.title,
                channel_id=channel_id,
                status="skipped",
                duration_sec=info.get("duration"),
                is_live_content=False,
            )
            state.upsert_stream(conn, stream)
            continue

        stream = Stream(
            video_id=entry.video_id,
            url=entry.url,
            title=entry.title,
            channel_id=channel_id,
            status="new",
            duration_sec=info.get("duration"),
            is_live_content=True,
        )
        state.upsert_stream(conn, stream)
        new_streams.append(stream)

    return DetectReport(
        channel_id=channel_id,
        scanned=len(entries),
        new_streams=new_streams,
        known=known,
        skipped_non_live=skipped_non_live,
        failed_probes=failed_probes,
    )


def unprocessed_streams(conn: sqlite3.Connection) -> list[Stream]:
    """Streams that still need work, oldest first."""
    active_statuses = ("new", "captions_pending", "transcribed")
    active = [s for s in state.list_streams(conn) if s.status in active_statuses]
    return sorted(active, key=lambda s: s.first_seen_at)
