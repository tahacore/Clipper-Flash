"""YouTube access helpers: RSS feeds, metadata probes, channel resolution.

All network functions are thin and injectable so callers (and tests) can
swap transports without hitting the network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

import feedparser
import httpx

RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
WATCH_URL = "https://www.youtube.com/watch?v={video_id}"

_CHANNEL_ID_RE = re.compile(r"(UC[\w-]{22})")


class YouTubeError(RuntimeError):
    pass


@dataclass
class RssEntry:
    video_id: str
    title: str
    url: str
    published: datetime | None


def fetch_rss_xml(channel_id: str, timeout: float = 20.0) -> str:
    resp = httpx.get(RSS_URL.format(channel_id=channel_id), timeout=timeout, follow_redirects=True)
    if resp.status_code == 404:
        raise YouTubeError(f"channel not found (bad channel_id?): {channel_id}")
    resp.raise_for_status()
    return resp.text


def parse_rss(xml_text: str) -> list[RssEntry]:
    """Parse a channel uploads RSS feed into entries (newest first)."""
    feed = feedparser.parse(xml_text)
    if feed.bozo and not feed.entries:
        raise YouTubeError(f"failed to parse RSS feed: {feed.bozo_exception}")
    entries: list[RssEntry] = []
    for e in feed.entries:
        video_id = getattr(e, "yt_videoid", None)
        if not video_id:
            continue
        published = None
        parsed = getattr(e, "published_parsed", None)
        if parsed:
            published = datetime.fromtimestamp(datetime(*parsed[:6]).timestamp())
        entries.append(
            RssEntry(
                video_id=video_id,
                title=getattr(e, "title", "") or "",
                url=WATCH_URL.format(video_id=video_id),
                published=published,
            )
        )
    return entries


def probe_video(url: str, timeout: float = 60.0) -> dict:
    """Fetch lightweight metadata for a video via yt-dlp (no download)."""
    import yt_dlp

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        "socket_timeout": timeout,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise YouTubeError(f"could not extract metadata for {url}")
    return info


def extract_video_id(ref: str) -> str | None:
    """Accept raw IDs, watch URLs, youtu.be links."""
    ref = ref.strip()
    if re.fullmatch(r"[\w-]{11}", ref):
        return ref
    m = re.search(r"(?:v=|youtu\.be/|shorts/|live/)([\w-]{11})", ref)
    return m.group(1) if m else None


def resolve_channel_id(ref: str) -> str:
    """Resolve a channel reference (UC id, @handle, or any channel/video URL)."""
    ref = ref.strip()
    m = _CHANNEL_ID_RE.search(ref)
    if m:
        return m.group(1)

    # Try a metadata probe; works for @handle URLs and plain video URLs.
    candidates = [ref]
    if ref.startswith("@"):
        candidates = [f"https://www.youtube.com/{ref}"]
    elif extract_video_id(ref):
        vid = extract_video_id(ref)
        assert vid is not None
        candidates = [WATCH_URL.format(video_id=vid)]

    for cand in candidates:
        try:
            info = probe_video(cand)
        except Exception:  # noqa: BLE001 - try next candidate form
            continue
        cid = info.get("channel_id") or ""
        if _CHANNEL_ID_RE.fullmatch(cid):
            return cid
    raise YouTubeError(
        f"could not resolve channel id from {ref!r}. "
        "Tip: use the channel's UC... id from its page source or About > Share channel."
    )
