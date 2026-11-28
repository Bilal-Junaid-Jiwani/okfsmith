"""Tests for ``okfsmith diff`` (CLI) and ``okfsmith.core.diff``.

The ``diff`` comparison existed only as an MCP tool — a terminal user had
no way to ask "what changed since the last sync?" without an MCP client.
The CLI command renders the same comparison (same row shapes, same
temporal notes, same trust rules for sync-state manifest paths) as text
or ``--format json``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from okfsmith.cli.app import app
from okfsmith.core import Bundle
from okfsmith.core.diff import (
    DiffError,
    diff_against_sync_state,
    diff_bundles,
)

runner = CliRunner()
WIDE = {"COLUMNS": "200"}


def _write_bundle(root: Path, files: dict[str, str]) -> Bundle:
    """Write *files* (rel path → text) under *root* and load as a bundle."""
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return Bundle.load(root)


def _concept_doc(title: str, body: str, extra_fm: str = "") -> str:
    return f"---\ntitle: {title}\n{extra_fm}---\n\n{body}\n"


def _diff_bundles(tmp_path: Path) -> tuple[Path, Path]:
    _write_bundle(
        tmp_path / "old",
        {
            "keep.md": _concept_doc("Keep", "same body\n"),
            "gone.md": _concept_doc("Gone", "will be removed\n"),
            "edit.md": _concept_doc("Edit", "original body\n"),
        },
    )
    _write_bundle(
        tmp_path / "new",
        {
            "keep.md": _concept_doc("Keep", "same body\n"),
            "fresh.md": _concept_doc("Fresh", "brand new\n"),
            "edit.md": _concept_doc("Edit", "changed body\n"),
        },
    )
    return tmp_path / "old", tmp_path / "new"


def _sync_state_bundle(tmp_path: Path) -> Path:
    """Bundle with a sync-state snapshot: ``a`` changed, ``vanished`` removed."""
    kb = tmp_path / "kb"
    _write_bundle(
        kb,
        {
            "a.md": _concept_doc("Aye", "body a\n"),
            "b.md": _concept_doc("Bee", "body b\n"),
        },
    )
    # The recorded source lives inside the bundle root (manifest paths
    # outside the root are untrusted and never hashed), but it must not be
    # a ``.md`` file — Bundle would read it as a concept of its own.
    src_a = kb / "src_a.txt"
    src_a.write_text("v1 content", encoding="utf-8")
    digest_v1 = hashlib.sha256(b"v1 content").hexdigest()
    state_dir = kb / ".okfsmith"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "sync-state.json").write_text(
        json.dumps(
            {
                "version": 1,
                "sources": {
                    "src_a.txt": {
                        "sha256": digest_v1,
                        "concepts": ["a", "vanished"],
                        "size": 10,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    # The recorded source file changed since the snapshot → "a" is changed.
    src_a.write_text("v2 content", encoding="utf-8")
    return kb


# ---------------------------------------------------------------------------
# core: diff_bundles
# ---------------------------------------------------------------------------


def test_diff_bundles_sections(tmp_path: Path) -> None:
    old_root, new_root = _diff_bundles(tmp_path)
    result = diff_bundles(Bundle.load(new_root), Bundle.load(old_root))
    assert result.mode == "against"
    assert result.counts() == {"added": 1, "removed": 1, "changed": 1}
    assert [row.id for row in result.added] == ["fresh"]
    assert [row.id for row in result.removed] == ["gone"]
    assert [row.id for row in result.changed] == ["edit"]
    assert result.added[0].title == "Fresh"
    assert result.removed[0].title == "Gone"
    # Body SHAs come from the loaded concepts: Bundle normalizes the body
    # text, so hash the loaded body, not the raw fixture string.
    old_sha = hashlib.sha256(Bundle.load(old_root).get("edit").body.encode()).hexdigest()
    new_sha = hashlib.sha256(Bundle.load(new_root).get("edit").body.encode()).hexdigest()
    assert result.changed[0].old_sha256 == old_sha
    assert result.changed[0].new_sha256 == new_sha
    assert result.changed[0].source is None
    # Unchanged concepts never appear; every row carries a temporal status.
    assert all(row.temporal_status == "current" for row in result.added)
    assert all(row.temporal_status == "current" for row in result.removed)


def test_diff_bundles_no_changes(tmp_path: Path) -> None:
    old_root, _ = _diff_bundles(tmp_path)
    result = diff_bundles(Bundle.load(old_root), Bundle.load(old_root))
    assert result.counts() == {"added": 0, "removed": 0, "changed": 0}


def test_diff_bundles_title_only_change_counts(tmp_path: Path) -> None:
    old_root, new_root = _diff_bundles(tmp_path)
    # Same body, different title: still "changed" (titles are what readers see).
    (new_root / "edit.md").write_text(
        _concept_doc("Edit, retitled", "original body\n"), encoding="utf-8"
    )
    result = diff_bundles(Bundle.load(new_root), Bundle.load(old_root))
    assert [row.id for row in result.changed] == ["edit"]
    assert result.changed[0].title == "Edit, retitled"


def test_diff_bundles_as_of_replay(tmp_path: Path) -> None:
    """A concept past its ``valid_until`` reads expired at now, current at replay."""
    _write_bundle(
        tmp_path / "old",
        {"edit.md": _concept_doc("Edit", "original body\n")},
    )
    _write_bundle(
        tmp_path / "new",
        {
            "edit.md": _concept_doc(
                "Edit", "changed body\n", extra_fm="valid_until: 2026-11-01\n"
            ),
        },
    )
    result = diff_bundles(
        Bundle.load(tmp_path / "new"),
        Bundle.load(tmp_path / "old"),
        as_of=None,
    )
    assert result.changed[0].temporal_status == "expired"
    replayed = diff_bundles(
        Bundle.load(tmp_path / "new"),
        Bundle.load(tmp_path / "old"),
        as_of=datetime(2025, 6, 1, tzinfo=timezone.utc),
    )
    assert replayed.changed[0].temporal_status == "current"


# ---------------------------------------------------------------------------
# core: diff_against_sync_state
# ---------------------------------------------------------------------------


def test_diff_sync_state_sections(tmp_path: Path) -> None:
    kb = _sync_state_bundle(tmp_path)
    result = diff_against_sync_state(Bundle.load(kb))
    assert result.mode == "sync-state"
    assert result.counts() == {"added": 1, "removed": 1, "changed": 1}
    assert [row.id for row in result.added] == ["b"]
    assert [row.id for row in result.removed] == ["vanished"]
    # Removed rows honestly report no title/sha: the snapshot records ids only.
    assert result.removed[0].title is None
    assert result.removed[0].sha256 is None
    assert result.removed[0].temporal_status is None
    assert [row.id for row in result.changed] == ["a"]
    assert result.changed[0].source == "src_a.txt"
    assert result.changed[0].old_sha256 == hashlib.sha256(b"v1 content").hexdigest()
    assert result.changed[0].new_sha256 == hashlib.sha256(b"v2 content").hexdigest()
    assert result.source_records == 1
    assert result.untrusted == 0


def test_diff_sync_state_missing_is_clean_error(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    _write_bundle(kb, {"a.md": _concept_doc("Aye", "body\n")})
    with pytest.raises(DiffError) as excinfo:
        diff_against_sync_state(Bundle.load(kb))
    assert excinfo.value.code == "no-snapshot"
    assert "sync-state.json" in excinfo.value.message
    assert excinfo.value.hint and "--against" in excinfo.value.hint


def test_diff_sync_state_corrupt_is_clean_error(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    _write_bundle(kb, {"a.md": _concept_doc("Aye", "body\n")})
    state_dir = kb / ".okfsmith"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "sync-state.json").write_text("not json {{{", encoding="utf-8")
    with pytest.raises(DiffError) as excinfo:
        diff_against_sync_state(Bundle.load(kb))
    assert excinfo.value.code == "no-snapshot"


def test_diff_sync_state_untrusted_outside_path(tmp_path: Path) -> None:
    """A manifest path outside the bundle root is never hashed or echoed."""
    kb = tmp_path / "kb"
    _write_bundle(kb, {"a.md": _concept_doc("Aye", "body a\n")})
    outside = tmp_path / "secret.md"
    outside.write_text("host secret", encoding="utf-8")
    state_dir = kb / ".okfsmith"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "sync-state.json").write_text(
        json.dumps(
            {
                "version": 1,
                "sources": {
                    str(outside): {
                        "sha256": hashlib.sha256(b"host secret").hexdigest(),
                        "concepts": ["a"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    result = diff_against_sync_state(Bundle.load(kb))
    assert result.untrusted == 1
    assert result.counts() == {"added": 1, "removed": 0, "changed": 0}
    # The outside path is never echoed anywhere in the result.
    assert all(str(outside) not in (row.source or "") for row in result.changed)
    assert all(str(outside) not in (row.title or "") for row in result.added)


# ---------------------------------------------------------------------------
# CLI: okfsmith diff
# ---------------------------------------------------------------------------


def test_cli_diff_against_text(tmp_path: Path) -> None:
    old_root, new_root = _diff_bundles(tmp_path)
    result = runner.invoke(
        app, ["diff", str(new_root), "--against", str(old_root)], env=WIDE
    )
    assert result.exit_code == 0, result.output
    assert "# Bundle diff" in result.output
    assert "## Added (1)" in result.output and "**fresh**" in result.output
    assert "## Removed (1)" in result.output and "**gone**" in result.output
    assert "## Changed (1)" in result.output and "**edit**" in result.output
    assert "**keep**" not in result.output
    assert f"against `{old_root}`" in result.output


def test_cli_diff_against_json(tmp_path: Path) -> None:
    old_root, new_root = _diff_bundles(tmp_path)
    result = runner.invoke(
        app,
        ["diff", str(new_root), "--against", str(old_root), "--format", "json"],
        env=WIDE,
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["mode"] == "against"
    assert payload["against"] == str(old_root)
    assert payload["counts"] == {"added": 1, "removed": 1, "changed": 1}
    assert [row["id"] for row in payload["added"]] == ["fresh"]
    assert [row["id"] for row in payload["removed"]] == ["gone"]
    assert payload["changed"][0]["id"] == "edit"
    assert payload["changed"][0]["old_sha256"] != payload["changed"][0]["new_sha256"]
    assert "as_of" in payload


def test_cli_diff_sync_state_text(tmp_path: Path) -> None:
    kb = _sync_state_bundle(tmp_path)
    result = runner.invoke(app, ["diff", str(kb)], env=WIDE)
    assert result.exit_code == 0, result.output
    assert "sync-state.json" in result.output
    assert "**b**" in result.output
    assert "**vanished**" in result.output
    assert "title/sha unavailable" in result.output
    assert "`src_a.txt`" in result.output
    assert str(kb / "src_a.txt") not in result.output


def test_cli_diff_no_snapshot_error(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    _write_bundle(kb, {"a.md": _concept_doc("Aye", "body\n")})
    result = runner.invoke(app, ["diff", str(kb)], env=WIDE)
    assert result.exit_code == 1, result.output
    assert "error [no-snapshot]:" in result.output
    assert "--against" in result.output


def test_cli_diff_no_snapshot_json_error(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    _write_bundle(kb, {"a.md": _concept_doc("Aye", "body\n")})
    result = runner.invoke(app, ["diff", str(kb), "--format", "json"], env=WIDE)
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "error"
    assert payload["code"] == "no-snapshot"


def test_cli_diff_bad_against(tmp_path: Path) -> None:
    _, new_root = _diff_bundles(tmp_path)
    result = runner.invoke(
        app, ["diff", str(new_root), "--against", "/does/not/exist"], env=WIDE
    )
    assert result.exit_code == 1, result.output
    assert "error [bad-against]:" in result.output
    assert "not a directory" in result.output


def test_cli_diff_bad_as_of(tmp_path: Path) -> None:
    _, new_root = _diff_bundles(tmp_path)
    result = runner.invoke(
        app, ["diff", str(new_root), "--as-of", "not-a-date"], env=WIDE
    )
    assert result.exit_code == 2, result.output


def test_cli_diff_as_of_labels_replay(tmp_path: Path) -> None:
    old_root, new_root = _diff_bundles(tmp_path)
    result = runner.invoke(
        app,
        ["diff", str(new_root), "--against", str(old_root), "--as-of", "2025-06-01"],
        env=WIDE,
    )
    assert result.exit_code == 0, result.output
    assert "_Replayed as of 2025-06-01" in result.output


def test_cli_diff_help(tmp_path: Path) -> None:
    result = runner.invoke(app, ["diff", "--help"], env=WIDE)
    assert result.exit_code == 0, result.output
    assert "--against" in result.output
    assert "--as-of" in result.output
    assert "--format" in result.output
