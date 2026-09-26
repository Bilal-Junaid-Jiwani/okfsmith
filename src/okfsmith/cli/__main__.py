"""`python -m okfsmith.cli` entry point (avoids the runpy double-import warning)."""

from okfsmith.cli.app import app

if __name__ == "__main__":
    app()
