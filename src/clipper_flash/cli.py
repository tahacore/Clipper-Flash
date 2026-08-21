import typer

from clipper_flash import __version__

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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
