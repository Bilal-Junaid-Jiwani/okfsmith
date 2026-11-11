"""Tests for scripts/check_docs_changelog.py.

The checker guards the docs changelog against the completeness gap
fixed in 0.25.1 (only 9 of 55 released versions were listed).

NOTE: the tmp fixtures deliberately use distinct basenames
(root-changelog.md / docs-changelog.md), NOT CHANGELOG.md /
changelog.md — on case-insensitive filesystems (macOS, Windows)
those two names are the same file, so the docs write would clobber
the root write and every "missing version" test would see [].
"""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_docs_changelog.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_docs_changelog", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_real_changelogs_are_complete():
    """The shipped changelogs must pass the check (no regression)."""
    mod = _load()
    assert mod.missing_versions(REPO_ROOT / "CHANGELOG.md", REPO_ROOT / "docs" / "src" / "changelog.md") == []


def test_missing_version_is_reported(tmp_path):
    mod = _load()
    root = tmp_path / "root-changelog.md"
    docs = tmp_path / "docs-changelog.md"
    root.write_text("## [0.2.0] - 2026-01-02\n\n## [0.1.0] - 2026-01-01\n", encoding="utf-8")
    docs.write_text("## [0.1.0] — 2026-01-01 {#v0-1-0}\n", encoding="utf-8")
    assert mod.missing_versions(root, docs) == ["0.2.0"]


def test_docs_only_versions_are_tolerated(tmp_path):
    """Docs-only entries (e.g. 0.4.0) must not fail the check."""
    mod = _load()
    root = tmp_path / "root-changelog.md"
    docs = tmp_path / "docs-changelog.md"
    root.write_text("## [0.1.0] - 2026-01-01\n", encoding="utf-8")
    docs.write_text(
        "## [0.2.0] — 2026-01-02 {#v0-2-0}\n\n## [0.1.0] — 2026-01-01 {#v0-1-0}\n",
        encoding="utf-8",
    )
    assert mod.missing_versions(root, docs) == []


def test_multiple_missing_versions_sorted(tmp_path):
    mod = _load()
    root = tmp_path / "root-changelog.md"
    docs = tmp_path / "docs-changelog.md"
    root.write_text(
        "## [0.10.0] - 2026-01-03\n\n## [0.2.0] - 2026-01-02\n\n## [0.1.0] - 2026-01-01\n",
        encoding="utf-8",
    )
    docs.write_text("## [0.1.0] — 2026-01-01 {#v0-1-0}\n", encoding="utf-8")
    assert mod.missing_versions(root, docs) == ["0.2.0", "0.10.0"]


def test_main_exits_zero_on_complete_tree(capsys):
    mod = _load()
    assert mod.main([]) == 0
    assert "complete" in capsys.readouterr().out
