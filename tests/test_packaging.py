"""Tests for okfsmith packaging: the web dashboard's frontend bundle.

Regression test for the 0.5.1 packaging bug: the PyPI wheel shipped only the
dashboard's .py files, so `okfsmith dashboard` on a pip-installed copy showed
the "frontend bundle has not been built yet" placeholder instead of the SPA.

Proves: pyproject.toml declares package-data for the dashboard's static/
bundle, and the bundle files exist in the source tree to be packaged.

Also pins the public-facing current-version claims (project website and
man page) to the version declared in pyproject.toml, so they cannot go
stale the way the website's "Latest release v0.6.0" and the man page's
"okfsmith 0.1.0" header did (fixed in 0.7.7).

Note: pyproject is parsed as text (not tomllib) so these tests also run on
Python 3.10, which CI still covers.
"""

import re
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
            f'[tool.setuptools.package-data] entry for "{package}" does not cover "{leaf}/*"'
        )


def _declared_version() -> str:
    """The version declared in pyproject.toml (text-parsed for Python 3.10)."""
    text = (WORKTREE / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
    assert match, "version not found in pyproject.toml"
    return match.group(1)


def test_website_states_current_release():
    """The project website must name the release pyproject.toml declares.

    Regression (0.7.7): the landing page said "Latest release v0.6.0" in its
    PyPI card and "okfsmith v0.6.0" in the footer while 0.7.6 was current —
    the same class of stale public claim as the dashboard hint fixed in
    0.7.6. Pin both mentions to the declared version so the next bump fails
    here until the page is updated too.
    """
    version = _declared_version()
    site = (WORKTREE / "docs" / "site" / "index.html").read_text(encoding="utf-8")
    assert f"Latest release v{version}" in site, (
        "docs/site/index.html does not state the current release; "
        f"expected 'Latest release v{version}'"
    )
    assert f"okfsmith v{version}" in site, (
        "docs/site/index.html footer does not state the current release; "
        f"expected 'okfsmith v{version}'"
    )


def test_man_page_states_current_version():
    """The man page header must carry the declared version.

    Regression (0.7.7): man/okfsmith.1 still said "okfsmith 0.1.0" in its
    .TH header. Pin it to pyproject.toml's version.
    """
    version = _declared_version()
    man = (WORKTREE / "man" / "okfsmith.1").read_text(encoding="utf-8")
    header = man.splitlines()[0]
    assert f'"okfsmith {version}"' in header, (
        f"man/okfsmith.1 header does not name the current version: {header!r}"
    )


def _registered_mcp_tools() -> list[str]:
    """Tool names registered by ``build_server``, parsed from its source.

    Parsed as text (not imported) so this test also runs in the CI test
    job, which installs only the ``test`` extra — no fastmcp.
    """
    source = (WORKTREE / "src" / "okfsmith" / "mcp_server" / "server.py").read_text(
        encoding="utf-8"
    )
    return re.findall(r"server\.tool\(tools\.(\w+)\)", source)


def test_mcp_docs_name_every_registered_tool():
    """Every tool ``build_server`` registers must be documented by name.

    Regression (0.7.8): the MCP docs and README described a five/eight-tool
    read-only server long after the governed write-back tools
    (``preview_write_concept``, ``write_concept``, ``update_concept``,
    ``audit_log``) shipped in 0.4.1, so the documented surface no longer
    matched the registered one. Pin both documents to the registrations.
    """
    registered = _registered_mcp_tools()
    assert len(registered) >= 12, (
        f"expected the twelve registered MCP tools, parsed {registered!r} "
        "from build_server — has build_server's registration shape changed?"
    )
    mcp_doc = (WORKTREE / "docs" / "src" / "mcp.md").read_text(encoding="utf-8")
    readme = (WORKTREE / "README.md").read_text(encoding="utf-8")
    for name in registered:
        assert f"`{name}`" in mcp_doc, (
            f"docs/src/mcp.md does not document the registered MCP tool {name!r}"
        )
        assert f"`{name}`" in readme, (
            f"README.md does not document the registered MCP tool {name!r}"
        )


def test_mcp_docs_do_not_claim_read_only():
    """The MCP docs/README must not claim the server cannot write.

    Regression (0.7.8): docs/src/mcp.md called the server "fully read-only"
    with "no tool that writes, edits, or deletes concepts" and promised the
    bundle "is never modified" — false since the governed write-back tools
    shipped in 0.4.1, and a safety-relevant falsehood: a user could point an
    agent at a bundle believing writes were impossible. The truthful claims
    (the eight read tools cannot modify a bundle; writes are governed) do
    not use these phrases.
    """
    false_claims = (
        "fully **read-only**",
        "is never modified",
        "there is no tool that writes",
        "read-only MCP (Model",
    )
    for relpath in ("docs/src/mcp.md", "README.md", "docs/src/cli.md"):
        text = (WORKTREE / relpath).read_text(encoding="utf-8")
        for claim in false_claims:
            assert claim not in text, (
                f"{relpath} still claims the MCP server cannot write: {claim!r}"
            )
