"""okfsmith command-line interface.

Typer app wiring: the ``--version`` callback lives here and every command is
registered from :mod:`okfsmith.cli.commands` (imported for its side effect).
"""

from __future__ import annotations

import typer

from okfsmith import __version__

app = typer.Typer(
    help="Convert messy documents into OKF v0.2 knowledge bundles.",
    add_completion=False,
    # invoke_without_command=True lets the callback run on a bare `okfsmith`
    # so it can print help and exit 0 instead of "Missing command." (exit 2).
    invoke_without_command=True,
    epilog="New here? Run 'okfsmith init ./kb' to start a bundle, "
    "or 'okfsmith doctor' to check your setup.",
    rich_markup_mode="rich",
)


def _version_callback(value: bool) -> None:
    """Print the version and exit when ``--version`` is passed."""
    if value:
        typer.echo(f"okfsmith {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    version: bool | None = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the okfsmith version and exit.",
    ),
) -> None:
    """okfsmith — forge messy documents into OKF v0.2 knowledge bundles."""
    # Bare `okfsmith` prints help and exits 0 (friendlier than a usage error).
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()
