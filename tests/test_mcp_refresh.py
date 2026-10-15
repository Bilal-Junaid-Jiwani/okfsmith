"""Regression tests: the MCP server must reflect on-disk bundle changes
without a restart.

Before this fix the bundle was loaded once at server startup, so concepts
added/edited/deleted by the CLI (or any other process) stayed invisible to
the read tools until the server restarted. Each read tool now re-checks a
cheap on-disk fingerprint and reloads when it changed.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from okfsmith.core import Bundle
from okfsmith.mcp_server.server import BundleTools


def _make_bundle(tmp_path: Path, docs: dict[str, str]) -> Bundle:
    """Write *docs* ({filename: text}) into *tmp_path* and load a Bundle."""
    for name, text in docs.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return Bundle.load(tmp_path)


def _touch(path: Path) -> None:
    """Advance *path*'s mtime deterministically (same-tick writes can share
    mtime_ns on coarse filesystems; a real external edit always advances
    the clock)."""
    now = time.time() + 5
    os.utime(path, (now, now))


def test_post_start_add_visible_without_restart(tmp_path: Path) -> None:
    tools = BundleTools(_make_bundle(tmp_path, {"a.md": "---\ntitle: A\n---\nbody\n"}))
    assert "newcomer" not in tools.list()
    new_file = tmp_path / "newcomer.md"
    new_file.write_text("---\ntitle: Newcomer\n---\nadded after startup\n", encoding="utf-8")
    _touch(new_file)
    # No restart: the same BundleTools instance must see the new concept.
    assert "newcomer" in tools.list()
    assert "added after startup" in tools.get("newcomer")


def test_post_start_edit_visible_without_restart(tmp_path: Path) -> None:
    tools = BundleTools(_make_bundle(tmp_path, {"a.md": "---\ntitle: A\n---\nold body\n"}))
    assert "old body" in tools.get("a")
    concept_file = tmp_path / "a.md"
    concept_file.write_text("---\ntitle: A\n---\nnew body\n", encoding="utf-8")
    _touch(concept_file)
    assert "new body" in tools.get("a")


def test_post_start_delete_visible_without_restart(tmp_path: Path) -> None:
    tools = BundleTools(
        _make_bundle(
            tmp_path,
            {
                "a.md": "---\ntitle: A\n---\nbody\n",
                "gone.md": "---\ntitle: Gone\n---\nbody\n",
            },
        )
    )
    assert "gone" in tools.list()
    (tmp_path / "gone.md").unlink()
    assert "gone" not in tools.list()
    assert "not found" in tools.get("gone")


def test_no_reload_when_nothing_changed(tmp_path: Path) -> None:
    tools = BundleTools(_make_bundle(tmp_path, {"a.md": "---\ntitle: A\n---\nbody\n"}))
    before = tools.bundle
    tools.list()
    tools.search("body")
    # Fingerprint unchanged: no re-parse, the same in-memory Bundle serves.
    assert tools.bundle is before
