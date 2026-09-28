"""Tests for okfsmith packaging: the web dashboard's frontend bundle.

Regression test for the 0.5.1 packaging bug: the PyPI wheel shipped only the
dashboard's .py files, so `okfsmith dashboard` on a pip-installed copy showed
the "frontend bundle has not been built yet" placeholder instead of the SPA.

Proves: pyproject.toml declares package-data for the dashboard's static/
bundle, and the bundle files exist in the source tree to be packaged.

Note: pyproject is parsed as text (not tomllib) so these tests also run on
Python 3.10, which CI still covers.
"""

from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
STATIC_DIR = WORKTREE / "src" / "okfsmith" / "dashboard" / "static"
REQUIRED_BUNDLE_FILES = ("index.html", "app.js", "styles.css", "favicon.svg")

# Runtime data directories loaded via Path(__file__).parent. If you add a new
# one, add it here AND to [tool.setuptools.package-data] in pyproject.toml,
# or pip installs will silently miss it (the 0.5.1 dashboard bug).
RUNTIME_DATA_DIRS = {
    "okfsmith.dashboard": "static",
}


def _package_data_section() -> str:
    """Return the raw text of [tool.setuptools.package-data] from pyproject."""
    text = (WORKTREE / "pyproject.toml").read_text(encoding="utf-8")
    marker = "[tool.setuptools.package-data]"
    assert marker in text, "pyproject.toml is missing [tool.setuptools.package-data]"
    section = text.split(marker, 1)[1]
    lines = []
    for line in section.splitlines()[1:]:
        if line.startswith("["):
            break
        lines.append(line)
    return "\n".join(lines)


def test_dashboard_static_bundle_exists_in_source_tree():
    """The SPA files the server looks for must exist next to app.py."""
    for name in REQUIRED_BUNDLE_FILES:
        assert (STATIC_DIR / name).is_file(), f"missing dashboard static file: {name}"


def test_all_runtime_data_dirs_are_packaged():
    """Every runtime data dir must be declared in package-data (0.5.1 bug)."""
    section = _package_data_section()
    for package, leaf in RUNTIME_DATA_DIRS.items():
        data_dir = WORKTREE / "src" / Path(*package.split(".")) / leaf
        assert data_dir.is_dir(), f"runtime data dir missing from source: {data_dir}"
        assert f'"{package}"' in section, (
            f'[tool.setuptools.package-data] has no entry for "{package}"'
        )
        assert f"{leaf}/*" in section, (
            f'[tool.setuptools.package-data] entry for "{package}" does not '
            f'cover "{leaf}/*"'
        )
