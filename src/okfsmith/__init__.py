"""okfsmith — Documents → OKF knowledge bundles.

Converts messy documents (PDFs, markdown, wikis, exports) into Google's
Open Knowledge Format (OKF) v0.2 knowledge bundles: markdown files with
YAML frontmatter, plus reserved ``index.md`` / ``log.md`` files.
"""

from importlib.metadata import PackageNotFoundError, version


def _installed_version() -> str:
    """Single source of truth: the installed distribution's version.

    Falls back to reading ``pyproject.toml`` when the package is used from
    a bare checkout without install metadata (dev / tests), so there is no
    second hardcoded version string to rot.
    """
    try:
        return version("okfsmith")
    except PackageNotFoundError:
        pass
    try:
        import re
        from pathlib import Path

        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        m = re.search(
            r'^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"), re.M
        )
        if m:
            return m.group(1)
    except OSError:
        pass
    return "0.0.0+unknown"


__version__ = _installed_version()
