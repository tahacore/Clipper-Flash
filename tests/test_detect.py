import sqlite3
from pathlib import Path

from clipper_flash import state
from clipper_flash.detect import detect_new_streams, unprocessed_streams
from clipper_flash.youtube import RssEntry

RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015">
  <entry>
    <yt:videoId>AAAAAAAAAAA</yt:videoId>
    <title>Long coding stream</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=AAAAAAAAAAA"/>
    <published>2026-08-20T10:00:00+00:00</published>
  </entry>
  <entry>
    <yt:videoId>BBBBBBBBBBB</yt:videoId>
    <title>Short tutorial video</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=BBBBBBBBBBB"/>
    <published>2026-08-19T10:00:00+00:00</published>
  </entry>
</feed>
"""


CHANNEL = "UC1234567890123456789012"


def entries(_xml: str) -> list[RssEntry]:
    return [
        RssEntry(
            "AAAAAAAAAAA",
            "Long coding stream",
            "https://www.youtube.com/watch?v=AAAAAAAAAAA",
            None,
        ),
        RssEntry(
            "BBBBBBBBBBB",
            "Short tutorial video",
            "https://www.youtube.com/watch?v=BBBBBBBBBBB",
            None,
        ),
    ]


def fake_probe(url: str) -> dict:
    if "AAAAAAAAAAA" in url:
        return {"live_broadcast_content": "was_live", "duration": 25200, "channel_id": CHANNEL}
    return {"live_broadcast_content": "not_live", "duration": 600, "channel_id": CHANNEL}


def make_conn(tmp_path: Path) -> sqlite3.Connection:
    return state.connect(tmp_path / "state.db")


def test_detect_marks_livestreams_and_skips_others(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    report = detect_new_streams(
        conn,
        CHANNEL,
        prober=fake_probe,
        rss_fetcher=lambda cid: RSS_XML,
        rss_parser=entries,
    )
    assert report.scanned == 2
    assert [s.video_id for s in report.new_streams] == ["AAAAAAAAAAA"]
    assert report.skipped_non_live == 1

    skipped = state.get_stream(conn, "BBBBBBBBBBB")
    assert skipped and skipped.status == "skipped"


def test_detect_is_idempotent(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    for _ in range(2):
        report = detect_new_streams(
            conn,
            CHANNEL,
            prober=fake_probe,
            rss_fetcher=lambda cid: RSS_XML,
            rss_parser=entries,
        )
    assert report.new_streams == []
    assert report.known == 2


def test_include_all_overrides_live_filter(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    report = detect_new_streams(
        conn,
        CHANNEL,
        include_all=True,
        prober=fake_probe,
        rss_fetcher=lambda cid: RSS_XML,
        rss_parser=entries,
    )
    assert len(report.new_streams) == 2


def test_unprocessed_orders_oldest_first(tmp_path: Path) -> None:
    conn = make_conn(tmp_path)
    detect_new_streams(
        conn,
        CHANNEL,
        include_all=True,
        prober=fake_probe,
        rss_fetcher=lambda cid: RSS_XML,
        rss_parser=entries,
    )
    pending = unprocessed_streams(conn)
    assert [s.video_id for s in pending] == ["AAAAAAAAAAA", "BBBBBBBBBBB"]
