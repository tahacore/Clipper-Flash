import json
import shutil
import typing as t
from pathlib import Path

import typer

from clipper_flash import __version__, state
from clipper_flash import detect as detect_mod

app = typer.Typer(
    name="cf",
    help="Clipper-Flash: turn YouTube livestreams into clips with your coding agent.",
    no_args_is_help=True,
)
pull_app = typer.Typer(
    name="pull", help="Download sections or audio from YouTube.", no_args_is_help=True
)
app.add_typer(pull_app)

EXIT_ERROR = 1
EXIT_RETRYABLE = 2


@app.callback()
def _root() -> None:
    """Clipper-Flash: turn YouTube livestreams into clips with your coding agent."""


def _fail(message: str, code: int = EXIT_ERROR) -> t.NoReturn:
    typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=code)


def _echo_json(payload: t.Any) -> None:
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))


# --- basics ------------------------------------------------------------------


@app.command()
def version() -> None:
    """Print the Clipper-Flash version."""
    typer.echo(f"clipper-flash {__version__}")


@app.command()
def doctor() -> None:
    """Verify system dependencies (ffmpeg, yt-dlp, vision extras, state DB)."""
    checks: list[tuple[str, bool, str]] = []

    for tool in ("ffmpeg", "ffprobe"):
        found = shutil.which(tool) is not None
        checks.append((tool, found, "on PATH" if found else "NOT FOUND - install FFmpeg"))

    try:
        import yt_dlp  # noqa: F401
        import yt_dlp as _ytdlp
        checks.append(("yt-dlp", True, f"python package v{_ytdlp.version.__version__}"))
    except Exception as exc:  # noqa: BLE001
        checks.append(("yt-dlp", False, str(exc)))

    try:
        import cv2  # noqa: F401
        import mediapipe  # noqa: F401

        checks.append(("vision extras", True, "mediapipe + opencv available"))
    except Exception:  # noqa: BLE001
        checks.append(
            (
                "vision extras",
                False,
                "missing - install with: uv tool install 'clipper-flash[vision]'",
            )
        )

    try:
        conn = state.connect()
        n = len(state.list_streams(conn))
        checks.append(("state db", True, f"{state.db_path()} ({n} streams)"))
    except Exception as exc:  # noqa: BLE001
        checks.append(("state db", False, str(exc)))

    ok = True
    for name, good, detail in checks:
        green = typer.style("OK  ", fg=typer.colors.GREEN)
        red = typer.style("FAIL", fg=typer.colors.RED)
        mark = green if good else red
        typer.echo(f"{mark} {name:14} {detail}")
        ok = ok and good
    raise typer.Exit(code=0 if ok else EXIT_ERROR)


# --- detection & streams -----------------------------------------------------


@app.command(name="detect")
def detect_cmd(
    channel: str = typer.Argument(
        ..., help="Channel id (UC...), @handle, or any channel/video URL."
    ),
    include_all: bool = typer.Option(
        False,
        "--include-all",
        help="Treat every upload as a candidate, not just former livestreams.",
    ),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Scan a channel for unprocessed uploads and record new ones."""
    conn = state.connect()
    try:
        report = detect_mod.detect_new_streams(conn, channel, include_all=include_all)
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))

    payload = {
        "channel_id": report.channel_id,
        "scanned": report.scanned,
        "known": report.known,
        "skipped_non_live": report.skipped_non_live,
        "new_streams": [_stream_dict(s) for s in report.new_streams],
    }
    if as_json:
        _echo_json(payload)
        return

    typer.echo(f"channel:   {report.channel_id}")
    typer.echo(f"scanned:   {report.scanned} recent uploads")
    typer.echo(f"known:     {report.known} already tracked")
    if report.skipped_non_live:
        typer.echo(f"skipped:   {report.skipped_non_live} non-livestream uploads")
    if not report.new_streams:
        typer.echo("new:       nothing to process")
        return
    typer.echo("new:")
    for s in report.new_streams:
        dur = f", {s.duration_sec / 3600:.1f}h" if s.duration_sec else ""
        typer.echo(f"  - {s.video_id}  {s.title!r}{dur}")
        typer.echo(f"    {s.url}")


@app.command()
def streams(
    status: str = typer.Option(None, "--status", help="Filter by status."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """List tracked streams and their pipeline status."""
    conn = state.connect()
    items = state.list_streams(conn, status=status)
    if as_json:
        _echo_json([_stream_dict(s) for s in items])
        return
    if not items:
        typer.echo("no streams tracked yet - run 'cf detect <channel>' first")
        return
    for s in items:
        dur = f"{s.duration_sec / 3600:.1f}h" if s.duration_sec else "?"
        typer.echo(f"{s.status:>16}  {s.video_id}  {dur:>6}  {s.title}")


# --- transcript --------------------------------------------------------------


@app.command()
def transcript(
    url: str = typer.Argument(..., help="Video URL or id."),
    out: Path = typer.Option(None, "-o", "--out", help="Output json path."),
    lang: str = typer.Option("en", "--lang", help="Preferred caption language."),
    as_json: bool = typer.Option(False, "--json", help="Print summary JSON instead of text."),
) -> None:
    """Fetch and clean YouTube captions into a transcript JSON."""
    from clipper_flash.transcript import CaptionsUnavailable, fetch_transcript

    out = out or Path("work") / "transcript.json"
    conn = state.connect()
    vid = url.split("v=")[-1].split("/")[0][:11]
    try:
        t = fetch_transcript(url, lang=lang)
    except CaptionsUnavailable as exc:
        known = state.get_stream(conn, vid)
        if known:
            state.set_stream_status(conn, vid, "captions_pending", error=str(exc))
        _fail(f"{exc} (exit code 2 = retry later)", code=EXIT_RETRYABLE)
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))

    t.save(out)
    known = state.get_stream(conn, t.video_id)
    if known:
        state.set_stream_status(conn, t.video_id, "transcribed")

    summary = {
        "video_id": t.video_id,
        "language": t.language,
        "source": t.source,
        "duration_sec": t.duration_sec,
        "word_count": len(t.words),
        "segment_count": len(t.segments),
        "saved_to": str(out),
    }
    if as_json:
        _echo_json(summary)
        return
    typer.echo(f"transcript: {t.word_count} words, {len(t.segments)} segments "
               f"({t.source}/{t.language}) -> {out}")


# --- pull --------------------------------------------------------------------


@pull_app.command(name="section")
def pull_section_cmd(
    url: str = typer.Argument(..., help="Video URL or id."),
    start: str = typer.Argument(..., help="Start time ('4980' or '1:23:00')."),
    end: str = typer.Argument(..., help="End time."),
    out: Path = typer.Option(None, "-o", "--out", help="Output mp4 path."),
    max_height: int = typer.Option(1080, "--max-height", help="Cap source resolution."),
) -> None:
    """Download exactly one section at full quality (keyframe-exact cuts)."""
    from clipper_flash.pull import parse_time, pull_section

    out = out or Path("work") / "section.mp4"
    try:
        result = pull_section(url, parse_time(start), parse_time(end), out, max_height=max_height)
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))
    typer.echo(f"saved {result.path}")


@pull_app.command(name="audio")
def pull_audio_cmd(
    url: str = typer.Argument(..., help="Video URL or id."),
    out: Path = typer.Option(None, "-o", "--out", help="Output m4a path."),
) -> None:
    """Download audio-only track (for offline transcription fallback)."""
    from clipper_flash.pull import pull_audio

    out = out or Path("work") / "audio.m4a"
    try:
        result = pull_audio(url, out)
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))
    typer.echo(f"saved {result.path}")


# --- facecam -----------------------------------------------------------------


@app.command()
def facecam(
    video: Path = typer.Argument(..., help="Local video file (e.g. a pulled section)."),
    samples: int = typer.Option(12, "--samples", help="Frames to sample."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Detect the facecam region of a stream layout (sample-and-vote)."""
    from clipper_flash.facecam import FacecamNotFound, detect_facecam

    try:
        fc = detect_facecam(str(video), samples=samples)
    except FacecamNotFound as exc:
        _fail(f"{exc}", code=EXIT_RETRYABLE)
    except ImportError:
        _fail("vision extras missing - install with: uv tool install 'clipper-flash[vision]'")
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))
    if as_json:
        _echo_json(fc.to_dict())
        return
    typer.echo(f"facecam box: x={fc.x} y={fc.y} w={fc.w} h={fc.h} (confidence {fc.confidence})")


# --- render ------------------------------------------------------------------


@app.command()
def render(
    spec: Path = typer.Argument(..., help="Spec JSON file with a 'clips' array."),
    video_id: str = typer.Option(
        None, "--video-id", help="Register rendered clips to this stream."
    ),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Render clips described by a spec file."""
    from clipper_flash.render import RenderError, render_spec_file

    try:
        results = render_spec_file(spec)
    except RenderError as exc:
        _fail(str(exc))
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))

    if video_id:
        conn = state.connect()
        if state.get_stream(conn, video_id):
            for r in results:
                state.add_clip(
                    conn,
                    state.Clip(
                        stream_video_id=video_id,
                        start_sec=0.0,
                        end_sec=r.duration_sec,
                        title=Path(r.out).stem,
                        layout=r.layout,
                        status="rendered",
                        output_path=r.out,
                    ),
                )
            state.set_stream_status(conn, video_id, "clipped", mark_processed=True)

    payload = [
        {"out": r.out, "layout": r.layout, "size": f"{r.width}x{r.height}",
         "duration_sec": r.duration_sec, "captions": r.captions}
        for r in results
    ]
    if as_json:
        _echo_json(payload)
        return
    for p in payload:
        typer.echo(f"rendered [{p['layout']}] {p['size']} {p['duration_sec']}s -> {p['out']}")


# --- upload ------------------------------------------------------------------


@app.command()
def upload(
    file: Path = typer.Argument(..., help="Finished mp4 to upload."),
    title: str = typer.Option(..., "--title", help="Video title (<=100 chars)."),
    description: str = typer.Option("", "--desc", help="Video description."),
    privacy: str = typer.Option("unlisted", "--privacy", help="public | unlisted | private."),
    tags: str = typer.Option("", "--tags", help="Comma-separated tags."),
    client_secret: Path = typer.Option(
        Path("client_secret.json"), "--client-secret", help="OAuth desktop client secret JSON."
    ),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Upload a finished clip to YouTube (requires [upload] extra + OAuth setup)."""
    from clipper_flash.upload import UploadError, upload_video

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    try:
        result = upload_video(
            file, title, description, privacy=privacy, tags=tag_list,
            client_secret=client_secret,
        )
    except UploadError as exc:
        _fail(str(exc))
    except Exception as exc:  # noqa: BLE001
        _fail(f"upload failed: {exc}")
    if as_json:
        _echo_json({"video_id": result.video_id, "url": result.url, "privacy": result.privacy})
        return
    typer.echo(f"uploaded ({result.privacy}): {result.url}")


def _stream_dict(s: state.Stream) -> dict[str, t.Any]:
    return {
        "video_id": s.video_id,
        "url": s.url,
        "title": s.title,
        "status": s.status,
        "duration_sec": s.duration_sec,
        "is_live_content": s.is_live_content,
        "first_seen_at": s.first_seen_at,
        "error": s.error,
    }


def main() -> None:
    app()


if __name__ == "__main__":
    main()
