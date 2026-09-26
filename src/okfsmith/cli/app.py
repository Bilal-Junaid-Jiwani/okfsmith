"""okfsmith command-line interface.

Minimal Typer app: only the ``--version`` callback lives here for now.
The CLI engineer adds commands later — do not add commands in this module.
"""

from __future__ import annotations

import typer

from okfsmith import __version__

app = typer.Typer(
    help="Convert messy documents into OKF v0.2 knowledge bundles.",
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    """Print the version and exit when ``--version`` is passed."""
    if value:
        typer.echo(f"okfsmith {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool | None = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the okfsmith version and exit.",
    ),
) -> None:
    """okfsmith — Documents → OKF knowledge bundles."""
