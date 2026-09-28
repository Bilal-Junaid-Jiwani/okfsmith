"""okfsmith CLI package."""

# Importing commands registers them on the Typer app defined in
# ``okfsmith.cli.app`` (the app module itself stays command-free).
from okfsmith.cli import (  # noqa: F401
    commands,
    dashboard_cmd,
)
