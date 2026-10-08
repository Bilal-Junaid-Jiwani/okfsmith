"""The ``okfsmith dashboard`` command.

Purely additive: registers one Typer command on the shared app. FastAPI and
uvicorn are imported lazily inside the command so ``okfsmith`` stays usable
even if the dashboard extras are somehow missing (with a friendly error).
"""

from __future__ import annotations

from pathlib import Path

import typer

from okfsmith.cli.app import app


@app.command(rich_help_panel="Serve")
def dashboard(
    port: int = typer.Option(
        8931, "--port", help="Preferred port (next free port is used if taken)."
    ),
    no_open: bool = typer.Option(
        False, "--no-open", help="Do not open the browser automatically."
    ),
    dir: Path = typer.Option(
        Path("."),
        "--dir",
        help="Workspace root scanned for bundles (default: current directory).",
    ),
) -> None:
    """Serve the local okfsmith web dashboard (loopback only).

    Opens http://127.0.0.1:PORT/?token=... in your browser with a fresh
    per-launch token. The server binds 127.0.0.1 only — it is never
    reachable from the network.
    """
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError:
        typer.echo(
            "error [dashboard-deps-missing]: the dashboard needs 'fastapi' and "
            "'uvicorn'.\n"
            "hint: reinstall okfsmith ('pip install -U okfsmith') or run "
            "'pip install \"fastapi>=0.122,<0.143\" \"uvicorn>=0.35,<0.55\"'.",
            err=True,
        )
        raise typer.Exit(code=1) from None
    if not 1 <= port <= 65535:
        typer.echo(
            f"error [bad-port]: port must be 1-65535, got {port}.",
            err=True,
        )
        raise typer.Exit(code=2)
    workspace = dir.resolve()
    if not workspace.is_dir():
        typer.echo(
            f"error [bad-dir]: '{dir}' is not a directory.\n"
            "hint: pass an existing directory with --dir.",
            err=True,
        )
        raise typer.Exit(code=2)

    from okfsmith.dashboard.server import serve

    try:
        serve(workspace, port=port, no_open=no_open)
    except OSError as exc:
        # e.g. no free loopback port left at/above the requested one.
        typer.echo(f"error [dashboard-start-failed]: {exc}", err=True)
        raise typer.Exit(code=1) from None
