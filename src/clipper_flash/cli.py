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

        from clipper_flash.facecam import _YUNET_MODEL

        if _YUNET_MODEL.exists():
            checks.append(("vision extras", True, "opencv + yunet model"))
        else:
            checks.append(("vision extras", False, "yunet model missing - reinstall clipper-flash"))
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

    skill_src = _bundled_skill_dir()
    skill_locations = [
        Path.home() / ".claude" / "skills" / "clipper-flash" / "SKILL.md",
        Path.home() / ".agents" / "skills" / "clipper-flash" / "SKILL.md",
    ]
    found = [p for p in skill_locations if p.exists()]
    if found:
        checks.append(("agent skill", True, str(found[0])))
    else:
        checks.append(
            ("agent skill", False, "not installed - run: cf install-skill")
        )
    if skill_src is None:
        checks.append(("skill source", False, "SKILL.md missing from package"))

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
        "failed_probes": report.failed_probes,
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
    if report.failed_probes:
        typer.echo(
            f"unprobeable: {len(report.failed_probes)} (live/processing) - will retry next scan"
        )
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

    out.parent.mkdir(parents=True, exist_ok=True)
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
         "duration_sec": r.duration_sec, "captions": r.captions, "poster": r.poster}
        for r in results
    ]
    if as_json:
        _echo_json(payload)
        return
    for p in payload:
        typer.echo(f"rendered [{p['layout']}] {p['size']} {p['duration_sec']}s -> {p['out']}")


# --- skill installation ------------------------------------------------------

_SKILL_MARK_BEGIN = "<!-- CLIPPER-FLASH:BEGIN -->"
_SKILL_MARK_END = "<!-- CLIPPER-FLASH:END -->"


def _bundled_skill_dir() -> Path | None:
    """Locate the packaged SKILL.md (wheel) or repo copy (dev checkout)."""
    packaged = Path(__file__).parent / "_skills" / "clipper-flash"
    if packaged.exists():
        return packaged
    candidates = [
        Path.cwd() / "skills" / "clipper-flash",
        Path(__file__).resolve().parents[2] / "skills" / "clipper-flash",
    ]
    for cand in candidates:
        if (cand / "SKILL.md").exists():
            return cand
    return None


def _codex_agents_block(skill_ref: str) -> str:
    return (
        f"{_SKILL_MARK_BEGIN}\n"
        "## Clipper-Flash\n"
        "When asked to clip, find highlights in, or repurpose YouTube "
        "livestreams/VODs, follow the workflow in:\n"
        f"{skill_ref}\n"
        f"{_SKILL_MARK_END}"
    )


@app.command(name="install-skill")
def install_skill_cmd(
    claude_dir: Path = typer.Option(
        None, "--claude-dir", help="Override Claude Code skills directory."
    ),
    codex_home: Path = typer.Option(None, "--codex-home", help="Override ~/.codex location."),
    skip_codex: bool = typer.Option(False, "--skip-codex", help="Do not touch Codex config."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Install/update the Clipper-Flash skill for Claude Code and Codex."""
    import shutil as _shutil

    src = _bundled_skill_dir()
    if not src:
        _fail("SKILL.md not found next to the installed package - reinstall clipper-flash")

    results: dict[str, t.Any] = {}

    # Cross-agent standard location (Codex USER scope, adopted by other agents).
    agents_target = (
        codex_home.parent / ".agents" / "skills" / "clipper-flash"
        if codex_home
        else Path.home() / ".agents" / "skills" / "clipper-flash"
    )
    try:
        agents_target.mkdir(parents=True, exist_ok=True)
        _shutil.copy2(src / "SKILL.md", agents_target / "SKILL.md")
        results["agents"] = {"installed": True, "path": str(agents_target / "SKILL.md")}
    except OSError as exc:
        results["agents"] = {"installed": False, "error": str(exc)}

    # Claude Code personal skills
    claude_target = claude_dir or (Path.home() / ".claude" / "skills" / "clipper-flash")
    try:
        claude_target.mkdir(parents=True, exist_ok=True)
        _shutil.copy2(src / "SKILL.md", claude_target / "SKILL.md")
        results["claude"] = {"installed": True, "path": str(claude_target / "SKILL.md")}
    except OSError as exc:
        results["claude"] = {"installed": False, "error": str(exc)}

    # Codex global instructions (only if a codex home exists or was forced)
    codex_base = codex_home or (Path.home() / ".codex")
    if skip_codex:
        results["codex"] = {"installed": False, "skipped": True}
    elif codex_home is not None or codex_base.exists():
        agents = codex_base / "AGENTS.md"
        try:
            codex_base.mkdir(parents=True, exist_ok=True)
            existing = agents.read_text(encoding="utf-8") if agents.exists() else ""
            block = _codex_agents_block(str(claude_target / "SKILL.md"))
            if _SKILL_MARK_BEGIN in existing:
                pre = existing.split(_SKILL_MARK_BEGIN)[0].rstrip("\n")
                post = existing.split(_SKILL_MARK_END)[-1].lstrip("\n")
                new_content = (pre + "\n\n" + block + "\n\n" + post).strip() + "\n"
            else:
                new_content = (existing.rstrip("\n") + "\n\n" + block + "\n").lstrip("\n")
            agents.write_text(new_content, encoding="utf-8")
            results["codex"] = {"installed": True, "path": str(agents)}
        except OSError as exc:
            results["codex"] = {"installed": False, "error": str(exc)}
    else:
        results["codex"] = {
            "installed": False,
            "skipped": True,
            "hint": "no ~/.codex found; pass --codex-home to force",
        }

    if as_json:
        _echo_json(results)
        return
    for agent, info in results.items():
        if info.get("installed"):
            typer.echo(f"OK   {agent:8} -> {info['path']}")
        elif info.get("skipped"):
            hint = f" ({info['hint']})" if info.get("hint") else ""
            typer.echo(f"SKIP {agent:8}{hint}")
        else:
            typer.secho(f"FAIL {agent:8} {info.get('error')}", fg=typer.colors.RED)
    installed_anywhere = any(
        info.get("installed") for info in results.values()
    )
    if not installed_anywhere:
        _fail("could not install the skill anywhere")


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


# --- gallery UI --------------------------------------------------------------


@app.command()
def serve(
    port: int = typer.Option(8600, "--port", help="HTTP port."),
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address."),
) -> None:
    """Serve the clip gallery web UI."""
    try:
        import uvicorn

        from clipper_flash import server
    except ImportError:
        _fail("web extras missing - install with: uv tool install 'clipper-flash[web]'")
    typer.echo(f"gallery: http://{host}:{port}  (ctrl-c to stop)")
    uvicorn.run(server.app, host=host, port=port, log_level="warning")


@app.command(name="clear")
def clear_cmd(
    skipped_only: bool = typer.Option(False, "--skipped", help="Remove only skipped streams."),
    all_streams: bool = typer.Option(
        False, "--all", help="Remove ALL tracked data (streams+clips)."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Purge tracked streams/clips from local state."""
    conn = state.connect()
    if not any([skipped_only, all_streams]):
        _fail("choose --skipped or --all (nothing done)")
    if not yes and not as_json:
        scope = "ALL streams and clips" if all_streams else "skipped streams"
        if not typer.confirm(f"Delete {scope} from state?"):
            raise typer.Abort()

    if all_streams:
        n_clips = conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0]
        n_streams = conn.execute("SELECT COUNT(*) FROM streams").fetchone()[0]
        conn.execute("DELETE FROM clips")
        conn.execute("DELETE FROM streams")
    else:
        n_clips = conn.execute(
            "SELECT COUNT(*) FROM clips WHERE stream_video_id IN "
            "(SELECT video_id FROM streams WHERE status='skipped')"
        ).fetchone()[0]
        n_streams = conn.execute(
            "SELECT COUNT(*) FROM streams WHERE status='skipped'"
        ).fetchone()[0]
        conn.execute(
            "DELETE FROM clips WHERE stream_video_id IN "
            "(SELECT video_id FROM streams WHERE status='skipped')"
        )
        conn.execute("DELETE FROM streams WHERE status='skipped'")
    conn.commit()
    if as_json:
        _echo_json({"removed_streams": n_streams, "removed_clips": n_clips})
        return
    typer.echo(f"removed {n_streams} streams, {n_clips} clips")


# --- memory ------------------------------------------------------------------


memory_app = typer.Typer(
    name="memory", help="Channel memory: topics, stories, past clips.", no_args_is_help=True
)
app.add_typer(memory_app)


@memory_app.command(name="add")
def memory_add_cmd(
    text: str = typer.Argument(..., help="What to remember (summary, story note, clip note)."),
    kind: str = typer.Option("note", "--kind", help="stream_summary | clip_note | note."),
    video_id: str = typer.Option("", "--video-id", help="Associate with a video."),
    channel_id: str = typer.Option("", "--channel-id", help="Associate with a channel."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Write something to channel memory."""
    try:
        mid = state.add_memory(
            state.connect(), kind, text, channel_id=channel_id, video_id=video_id
        )
    except ValueError as exc:
        _fail(str(exc))
    if as_json:
        _echo_json({"id": mid})
        return
    typer.echo(f"remembered #{mid}")


@memory_app.command(name="list")
def memory_list_cmd(
    channel_id: str = typer.Option(None, "--channel-id", help="Filter by channel."),
    kind: str = typer.Option(None, "--kind", help="Filter by kind."),
    limit: int = typer.Option(50, "--limit", help="Max entries."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Recall channel memory (newest first)."""
    rows = state.list_memories(state.connect(), channel_id=channel_id, kind=kind, limit=limit)
    items = [
        {"id": r["id"], "kind": r["kind"], "video_id": r["video_id"],
         "created_at": r["created_at"], "text": r["text"]}
        for r in rows
    ]
    if as_json:
        _echo_json(items)
        return
    if not items:
        typer.echo("memory is empty")
        return
    for it in items:
        typer.echo(f"#{it['id']} [{it['kind']}] {it['created_at']} {it['text'][:110]}")


@memory_app.command(name="delete")
def memory_delete_cmd(
    memory_id: int = typer.Argument(..., help="Memory id to delete."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Delete one memory entry."""
    state.delete_memory(state.connect(), memory_id)
    if as_json:
        _echo_json({"deleted": memory_id})
        return
    typer.echo(f"deleted #{memory_id}")


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
