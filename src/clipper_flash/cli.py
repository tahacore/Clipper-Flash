import json
import typing as t

import typer

from clipper_flash import __version__, state
from clipper_flash import detect as detect_mod

app = typer.Typer(
    name="cf",
    help="Clipper-Flash: turn YouTube livestreams into clips with your coding agent.",
    no_args_is_help=True,
)


@app.callback()
def _root() -> None:
    """Clipper-Flash: turn YouTube livestreams into clips with your coding agent."""


@app.command()
def version() -> None:
    """Print the Clipper-Flash version."""
    typer.echo(f"clipper-flash {__version__}")


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

    if as_json:
        payload = {
            "channel_id": report.channel_id,
            "scanned": report.scanned,
            "known": report.known,
            "skipped_non_live": report.skipped_non_live,
            "new_streams": [_stream_dict(s) for s in report.new_streams],
        }
        typer.echo(json.dumps(payload, indent=2))
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


def _stream_dict(s: state.Stream) -> dict[str, t.Any]:
    return {
        "video_id": s.video_id,
        "url": s.url,
        "title": s.title,
        "status": s.status,
        "duration_sec": s.duration_sec,
        "is_live_content": s.is_live_content,
    }


def _fail(message: str) -> t.NoReturn:
    typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
