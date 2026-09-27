"""Tests for ``okfsmith sync`` (P1 — incremental sync).

Two layers:

- CLI/engine tests use the REAL parsers slice (``--no-llm``) end to end via
  ``typer.testing.CliRunner``: new/changed/deleted/renamed files,
  interrupted-resume, binary changes, empty sources, unicode filenames,
  watch mode, dry-run, and JSON output.
- Unit tests cover :mod:`okfsmith.core.sync` (plan classification, rename
  pairing, state I/O) plus the new ``Bundle.delete_concept`` and
  ``dedup.unrecord_digest`` helpers.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from okfsmith.cli import sync as sync_mod
from okfsmith.cli.app import app
from okfsmith.core import Bundle
from okfsmith.core import sync as core_sync
from okfsmith.parsers import dedup as dedup_mod

runner = CliRunner()
WIDE = {"COLUMNS": "200"}  # keep rich tables from truncating rows


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class SimpleNamespace:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _doc(path: Path, title: str, seed: str, paras: int = 25) -> Path:
    """Write a comfortably-above-the-stub-threshold markdown source."""
    body = "".join(
        f"{seed} paragraph {i}: " + "lorem ipsum dolor sit amet. " * 12 + "\n\n"
        for i in range(paras)
    )
    path.write_text(f"# {title}\n\n{body}", encoding="utf-8")
    assert len(path.read_text(encoding="utf-8")) > 1000
    return path


@pytest.fixture()
def synced(tmp_path):
    """An initialized bundle plus a source dir with two documents."""
    bundle = tmp_path / "kb"
    src = tmp_path / "src"
    src.mkdir()
    files = [_doc(src / "a.md", "Alpha", "alpha"), _doc(src / "b.md", "Beta", "beta")]
    result = runner.invoke(app, ["init", str(bundle)], env=WIDE)
    assert result.exit_code == 0, result.output
    first = runner.invoke(
        app, ["sync", str(bundle), str(src), "--no-llm", "--quiet"], env=WIDE
    )
    assert first.exit_code == 0, first.output
    return SimpleNamespace(bundle=bundle, src=src, files=files)


def _concept_ids(bundle: Path) -> list[str]:
    return sorted(c.id for c in Bundle.load(bundle).iter_concepts())


def _state(bundle: Path) -> dict:
    return json.loads((bundle / ".okfsmith" / "sync-state.json").read_text())


def _sync(bundle: Path, src: Path, *extra: str):
    return runner.invoke(
        app, ["sync", str(bundle), str(src), "--no-llm", *extra], env=WIDE
    )


# ---------------------------------------------------------------------------
# Lifecycle: add / unchanged / update / rename / remove
# ---------------------------------------------------------------------------


def test_sync_adds_new_files(tmp_path):
    bundle = tmp_path / "kb"
    src = tmp_path / "src"
    src.mkdir()
    _doc(src / "a.md", "Alpha", "alpha")
    _doc(src / "b.md", "Beta", "beta")
    runner.invoke(app, ["init", str(bundle)], env=WIDE)

    result = _sync(bundle, src)
    assert result.exit_code == 0, result.output
    assert "2 added" in result.output
    assert len(_concept_ids(bundle)) == 2

    saved = _state(bundle)
    assert saved["incomplete"] is False
    assert len(saved["sources"]) == 2
    for record in saved["sources"].values():
        assert len(record["sha256"]) == 64
        assert len(record["concepts"]) == 1


def test_sync_second_run_reports_unchanged(synced):
    result = _sync(synced.bundle, synced.src)
    assert result.exit_code == 0, result.output
    assert "2 unchanged" in result.output
    assert "0 added" in result.output


def test_sync_changed_file_reingests_without_duplicates(synced):
    before = _concept_ids(synced.bundle)
    synced.files[0].write_text(
        synced.files[0].read_text(encoding="utf-8") + "\n\nNew section. " * 80,
        encoding="utf-8",
    )
    result = _sync(synced.bundle, synced.src)
    assert result.exit_code == 0, result.output
    assert "1 updated" in result.output
    assert "1 unchanged" in result.output
    after = _concept_ids(synced.bundle)
    # Same ids (no -2/-3 duplicates), same count.
    assert after == before
    assert not any(cid.endswith(("-2", "-3")) for cid in after)


def test_sync_deleted_file_removes_concepts(synced):
    synced.files[1].unlink()
    result = _sync(synced.bundle, synced.src)
    assert result.exit_code == 0, result.output
    assert "1 removed" in result.output
    assert "removed 1 concept(s)" in result.output
    assert len(_concept_ids(synced.bundle)) == 1
    saved = _state(synced.bundle)
    assert len(saved["sources"]) == 1
    # validate still passes with the state file present.
    check = runner.invoke(app, ["validate", str(synced.bundle)], env=WIDE)
    assert check.exit_code == 0, check.output


def test_sync_renamed_file_preserves_concepts(synced):
    before = _concept_ids(synced.bundle)
    old, new = synced.files[0], synced.src / "renamed.md"
    old.rename(new)
    result = _sync(synced.bundle, synced.src)
    assert result.exit_code == 0, result.output
    assert "1 renamed" in result.output
    assert "0 removed" in result.output
    # Concept ids preserved (not delete+recreate).
    assert _concept_ids(synced.bundle) == before
    concept = Bundle.load(synced.bundle).get(before[0])
    assert concept is not None
    # Provenance now points at the new path.
    assert concept.frontmatter["resource"] == str(new.resolve())


def test_sync_rename_is_not_add_plus_delete(synced):
    old = synced.files[0]
    old.rename(synced.src / "renamed.md")
    result = runner.invoke(
        app, ["sync", str(synced.bundle), str(synced.src), "--no-llm", "--format", "json"],
        env=WIDE,
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    changes = [f["change"] for f in payload["files"]]
    assert "renamed" in changes
    assert "added" not in changes
    assert "removed" not in changes


def test_sync_reverted_content_reingests(synced):
    """A file changed A→B→A across syncs ends with live concepts, no dupes."""
    original = synced.files[0].read_bytes()
    synced.files[0].write_bytes(original + b"\n\nExtra. " * 200)
    assert _sync(synced.bundle, synced.src).exit_code == 0
    synced.files[0].write_bytes(original)  # revert to the original bytes
    result = _sync(synced.bundle, synced.src)
    assert result.exit_code == 0, result.output
    assert "1 updated" in result.output
    assert len(_concept_ids(synced.bundle)) == 2


def test_sync_updated_file_below_threshold_keeps_old_concepts(synced):
    """If the new content would be skipped, old concepts are kept (pre-flight)."""
    before = _concept_ids(synced.bundle)
    old_sha = _state(synced.bundle)["sources"][str(synced.files[0].resolve())]["sha256"]
    synced.files[0].write_text("# Tiny\n\ntoo short now.\n", encoding="utf-8")
    result = _sync(synced.bundle, synced.src)
    assert result.exit_code == 0, result.output
    assert "skipped" in result.output
    # Old concepts survive; the state still holds the old digest (retry later).
    assert _concept_ids(synced.bundle) == before
    saved = _state(synced.bundle)
    assert saved["sources"][str(synced.files[0].resolve())]["sha256"] == old_sha


def test_sync_duplicate_content_shares_then_releases(synced):
    """Identical files share concepts; deletion only removes unshared ones."""
    src = synced.src
    data = (src / "a.md").read_bytes()
    (src / "copy.md").write_bytes(data)
    result = _sync(synced.bundle, src)
    assert result.exit_code == 0, result.output
    assert "skipped (already ingested)" in result.output
    assert len(_concept_ids(synced.bundle)) == 2  # no duplicates created

    # Deleting the ingested original keeps the concepts (shared with copy).
    (src / "a.md").unlink()
    result = _sync(synced.bundle, src)
    assert result.exit_code == 0, result.output
    assert "also tracked by" in result.output
    assert len(_concept_ids(synced.bundle)) == 2

    # Deleting the last sharer removes them.
    (src / "copy.md").unlink()
    result = _sync(synced.bundle, src)
    assert result.exit_code == 0, result.output
    assert len(_concept_ids(synced.bundle)) == 1  # only b.md's concept left


# ---------------------------------------------------------------------------
# Edge inputs
# ---------------------------------------------------------------------------


def test_sync_binary_change_is_detected_and_skipped(tmp_path):
    bundle = tmp_path / "kb"
    src = tmp_path / "src"
    src.mkdir()
    blob = src / "data.bin"
    blob.write_bytes(b"\x00\x01\x02\x03" * 500)
    runner.invoke(app, ["init", str(bundle)], env=WIDE)

    first = _sync(bundle, src)
    assert first.exit_code == 0, first.output
    assert "skipped" in first.output
    assert _concept_ids(bundle) == []

    blob.write_bytes(b"\x04\x05\x06\x07" * 500)  # binary change: new hash
    second = _sync(bundle, src)
    assert second.exit_code == 0, second.output
    assert "skipped" in second.output  # re-detected, handled, no crash


def test_sync_empty_source_dir(tmp_path):
    bundle = tmp_path / "kb"
    src = tmp_path / "src"
    src.mkdir()
    runner.invoke(app, ["init", str(bundle)], env=WIDE)
    result = _sync(bundle, src)
    assert result.exit_code == 0, result.output
    assert "0 added" in result.output


def test_sync_unicode_filenames(tmp_path):
    bundle = tmp_path / "kb"
    src = tmp_path / "src"
    src.mkdir()
    uni = _doc(src / "café-notes-日本語.md", "Café", "café")
    runner.invoke(app, ["init", str(bundle)], env=WIDE)
    result = _sync(bundle, src)
    assert result.exit_code == 0, result.output
    assert "1 added" in result.output
    assert len(_concept_ids(bundle)) == 1
    saved = _state(bundle)
    assert str(uni.resolve()) in saved["sources"]


def test_sync_recursive(tmp_path):
    bundle = tmp_path / "kb"
    src = tmp_path / "src"
    nested = src / "nested"
    nested.mkdir(parents=True)
    _doc(nested / "deep.md", "Deep", "deep")
    runner.invoke(app, ["init", str(bundle)], env=WIDE)

    shallow = _sync(bundle, src)
    assert shallow.exit_code == 0
    assert "0 added" in shallow.output  # not recursive: nested file unseen

    deep = runner.invoke(
        app, ["sync", str(bundle), str(src), "--no-llm", "--recursive"], env=WIDE
    )
    assert deep.exit_code == 0, deep.output
    assert "1 added" in deep.output


def test_sync_source_not_found(tmp_path):
    bundle = tmp_path / "kb"
    runner.invoke(app, ["init", str(bundle)], env=WIDE)
    result = runner.invoke(
        app, ["sync", str(bundle), str(tmp_path / "nope"), "--no-llm"], env=WIDE
    )
    assert result.exit_code != 0
    assert "error [source-not-found]" in result.output
    assert "Traceback" not in result.output


def test_sync_deletions_scoped_to_given_sources(synced):
    """Syncing dirB must not delete concepts that came from dirA."""
    other = synced.bundle.parent / "other"
    other.mkdir()
    _doc(other / "c.md", "Gamma", "gamma")
    assert _sync(synced.bundle, other).exit_code == 0
    assert len(_concept_ids(synced.bundle)) == 3

    # Sync only the original src: c.md's concepts must survive.
    result = _sync(synced.bundle, synced.src)
    assert result.exit_code == 0, result.output
    assert len(_concept_ids(synced.bundle)) == 3


# ---------------------------------------------------------------------------
# Interrupted sync / resume
# ---------------------------------------------------------------------------


def test_sync_interrupted_resume_adopts_existing(synced):
    path = synced.bundle / ".okfsmith" / "sync-state.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved["incomplete"] = True
    # Simulate: ingest ran for a.md but its state entry was never saved.
    del saved["sources"][str(synced.files[0].resolve())]
    path.write_text(json.dumps(saved), encoding="utf-8")

    result = _sync(synced.bundle, synced.src)
    assert result.exit_code == 0, result.output
    assert "adopted" in result.output
    # No duplicates created by the resume.
    assert len(_concept_ids(synced.bundle)) == 2
    assert _state(synced.bundle)["incomplete"] is False


def test_sync_corrupt_state_file_recovers(synced):
    path = synced.bundle / ".okfsmith" / "sync-state.json"
    path.write_text("{ this is not json", encoding="utf-8")
    result = _sync(synced.bundle, synced.src)
    assert result.exit_code == 0, result.output
    # Concepts adopted from the previous ingest, not duplicated.
    assert len(_concept_ids(synced.bundle)) == 2
    assert _state(synced.bundle)["incomplete"] is False


def test_sync_adopts_previous_plain_ingest(tmp_path):
    """First-ever sync after a plain `ingest` adopts without duplicating."""
    bundle = tmp_path / "kb"
    src = tmp_path / "src"
    src.mkdir()
    _doc(src / "a.md", "Alpha", "alpha")
    runner.invoke(app, ["init", str(bundle)], env=WIDE)
    ingested = runner.invoke(
        app, ["ingest", str(bundle), str(src), "--no-llm", "--quiet"], env=WIDE
    )
    assert ingested.exit_code == 0, ingested.output
    before = _concept_ids(bundle)

    result = _sync(bundle, src)
    assert result.exit_code == 0, result.output
    assert "adopted" in result.output
    assert _concept_ids(bundle) == before


def test_sync_state_writes_leave_no_temp_files(synced):
    dotdir = synced.bundle / ".okfsmith"
    leftovers = [p for p in dotdir.iterdir() if p.suffix == ".tmp" or ".tmp" in p.name]
    assert leftovers == []


# ---------------------------------------------------------------------------
# Dry run / JSON / flags
# ---------------------------------------------------------------------------


def test_sync_dry_run_writes_nothing(tmp_path):
    bundle = tmp_path / "kb"
    src = tmp_path / "src"
    src.mkdir()
    _doc(src / "a.md", "Alpha", "alpha")
    runner.invoke(app, ["init", str(bundle)], env=WIDE)

    result = runner.invoke(
        app, ["sync", str(bundle), str(src), "--no-llm", "--dry-run"], env=WIDE
    )
    assert result.exit_code == 0, result.output
    assert "would ingest" in result.output
    assert "dry run" in result.output
    assert _concept_ids(bundle) == []
    assert not (bundle / ".okfsmith" / "sync-state.json").exists()


def test_sync_json_output_shape(synced):
    result = runner.invoke(
        app,
        ["sync", str(synced.bundle), str(synced.src), "--no-llm", "--format", "json"],
        env=WIDE,
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert set(payload) == {
        "bundle", "sources", "dry_run", "resumed", "summary", "files",
    }
    assert set(payload["summary"]) == {
        "added", "updated", "renamed", "removed", "unchanged", "skipped", "failed",
    }
    assert payload["dry_run"] is False
    assert payload["resumed"] is False
    assert payload["summary"]["unchanged"] == 2
    for row in payload["files"]:
        assert set(row) == {"path", "change", "old_path", "concepts", "detail"}


def test_sync_json_error_object(tmp_path):
    bundle = tmp_path / "kb"
    runner.invoke(app, ["init", str(bundle)], env=WIDE)
    result = runner.invoke(
        app,
        ["sync", str(bundle), str(tmp_path / "nope"), "--no-llm", "--format", "json"],
        env=WIDE,
    )
    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["status"] == "error"
    assert payload["code"] == "source-not-found"


def test_sync_dry_run_json(synced):
    synced.files[0].unlink()
    result = runner.invoke(
        app,
        [
            "sync", str(synced.bundle), str(synced.src), "--no-llm",
            "--dry-run", "--format", "json",
        ],
        env=WIDE,
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert payload["summary"]["removed"] == 1
    # Nothing was actually removed.
    assert len(_concept_ids(synced.bundle)) == 2


def test_sync_flag_conflicts(tmp_path):
    bundle = tmp_path / "kb"
    src = tmp_path / "src"
    src.mkdir()
    runner.invoke(app, ["init", str(bundle)], env=WIDE)
    base = ["sync", str(bundle), str(src), "--no-llm"]
    for extra in (["--watch", "--poll"], ["--interval", "0"], ["--dry-run", "--watch"]):
        result = runner.invoke(app, [*base, *extra], env=WIDE)
        assert result.exit_code == 2, (extra, result.output)
    # --model/--provider/--api-base/--api-key all conflict with --no-llm.
    for flag in ("--model", "--provider", "--api-base", "--api-key"):
        result = runner.invoke(app, [*base, flag, "x"], env=WIDE)
        assert result.exit_code == 2, (flag, result.output)


def test_sync_llm_unavailable_is_clean_error(tmp_path, monkeypatch):
    """The LLM path maps an unreachable backend to error [llm-unavailable]."""
    from okfsmith.extract import LLMUnavailableError

    bundle = tmp_path / "kb"
    src = tmp_path / "src"
    src.mkdir()
    _doc(src / "a.md", "Alpha", "alpha")
    runner.invoke(app, ["init", str(bundle)], env=WIDE)

    def boom(*args, **kwargs):
        raise LLMUnavailableError("no LLM reachable")

    monkeypatch.setattr(sync_mod, "_ingest_llm_one", boom)
    result = runner.invoke(app, ["sync", str(bundle), str(src)], env=WIDE)
    assert result.exit_code == 1
    assert "error [llm-unavailable]" in result.output
    assert "Traceback" not in result.output


def test_sync_llm_path_ingests(monkeypatch, tmp_path):
    """The LLM branch wires through (stubbed extraction, no network)."""
    bundle = tmp_path / "kb"
    src = tmp_path / "src"
    src.mkdir()
    target_file = _doc(src / "a.md", "Alpha", "alpha")
    runner.invoke(app, ["init", str(bundle)], env=WIDE)

    def fake_llm_one(path, target, **kwargs):
        target.write_concept(
            f"llm/{Path(path).stem}",
            {"type": "Note", "title": Path(path).stem,
             "resource": str(path)},
            "extracted body",
        )
        return ("ok", 1)

    monkeypatch.setattr(sync_mod, "_ingest_llm_one", fake_llm_one)
    result = runner.invoke(app, ["sync", str(bundle), str(src)], env=WIDE)
    assert result.exit_code == 0, result.output
    assert "1 added" in result.output
    assert _concept_ids(bundle) == ["llm/a"]
    saved = json.loads(
        (bundle / ".okfsmith" / "sync-state.json").read_text(encoding="utf-8")
    )
    assert saved["sources"][str(target_file.resolve())]["concepts"] == ["llm/a"]


# ---------------------------------------------------------------------------
# Watch mode
# ---------------------------------------------------------------------------


def test_sync_watch_detects_change(tmp_path, monkeypatch):
    bundle = tmp_path / "kb"
    src = tmp_path / "src"
    src.mkdir()
    target = _doc(src / "a.md", "Alpha", "alpha")
    runner.invoke(app, ["init", str(bundle)], env=WIDE)
    config = sync_mod.SyncConfig(no_llm=True)

    seen: list = []
    original = sync_mod.run_once

    def spy(bundle_path, sources, cfg, _wiring=None):
        result = original(bundle_path, sources, cfg, _wiring=_wiring)
        seen.append(result)
        return result

    monkeypatch.setattr(sync_mod, "run_once", spy)
    stop = threading.Event()
    thread = threading.Thread(
        target=sync_mod.run_watch,
        kwargs={
            "bundle_path": bundle,
            "sources": [src],
            "config": config,
            "interval": 0.05,
            "output_format": "text",
            "quiet": True,
            "stop_event": stop,
            "max_cycles": 600,
        },
        daemon=True,
    )
    try:
        thread.start()
        deadline = time.time() + 10
        while not seen and time.time() < deadline:
            time.sleep(0.05)
        assert seen, "initial watch pass never ran"

        target.write_text(
            target.read_text(encoding="utf-8") + "\n\nWatched change. " * 60,
            encoding="utf-8",
        )
        os.utime(target, None)

        deadline = time.time() + 15
        updated = False
        while time.time() < deadline:
            if any(r.summary()["updated"] for r in seen[1:]):
                updated = True
                break
            time.sleep(0.05)
        assert updated, "watch loop did not re-sync the modified file"
    finally:
        stop.set()
        thread.join(timeout=15)
        assert not thread.is_alive()


def test_sync_watch_keyboard_interrupt_exits_cleanly(tmp_path, monkeypatch, capsys):
    src = tmp_path / "src"
    src.mkdir()
    _doc(src / "a.md", "Alpha", "alpha")

    def boom(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(sync_mod, "run_once", boom)
    # Must return normally (no traceback, no hang).
    sync_mod.run_watch(
        tmp_path / "kb",
        [src],
        sync_mod.SyncConfig(no_llm=True),
        interval=60,
        output_format="text",
        quiet=True,
        stop_event=threading.Event(),
        max_cycles=1,
    )
    assert "stopped watching." in capsys.readouterr().err


def test_sync_watch_touch_without_change_does_not_resync(tmp_path, monkeypatch):
    """mtime-only change with identical SHA-256 must not trigger a sync pass."""
    bundle = tmp_path / "kb"
    src = tmp_path / "src"
    src.mkdir()
    target = _doc(src / "a.md", "Alpha", "alpha")
    runner.invoke(app, ["init", str(bundle)], env=WIDE)
    config = sync_mod.SyncConfig(no_llm=True)

    calls = []
    original = sync_mod.run_once

    def spy(bundle_path, sources, cfg, _wiring=None):
        calls.append(1)
        return original(bundle_path, sources, cfg, _wiring=_wiring)

    monkeypatch.setattr(sync_mod, "run_once", spy)
    stop = threading.Event()
    thread = threading.Thread(
        target=sync_mod.run_watch,
        kwargs={
            "bundle_path": bundle,
            "sources": [src],
            "config": config,
            "interval": 0.05,
            "output_format": "text",
            "quiet": True,
            "stop_event": stop,
            "max_cycles": 40,
        },
        daemon=True,
    )
    try:
        thread.start()
        deadline = time.time() + 10
        while not calls and time.time() < deadline:
            time.sleep(0.05)
        assert calls, "initial watch pass never ran"
        before = len(calls)
        # Touch: new mtime, same size, same content.
        new_mtime = time.time() + 5
        os.utime(target, (new_mtime, new_mtime))
        time.sleep(1.0)
        assert len(calls) == before, "bare touch triggered a redundant sync"
    finally:
        stop.set()
        thread.join(timeout=15)
        assert not thread.is_alive()


# ===========================================================================
# Unit tests: okfsmith.core.sync
# ===========================================================================


def _entry(sha: str, concepts=("x/c",)) -> dict:
    return {
        "sha256": sha,
        "concepts": list(concepts),
        "size": 10,
        "mtime_ns": 1,
    }


def test_plan_sync_classifies_all_changes():
    current = {
        "/s/added.md": "sha-new",
        "/s/changed.md": "sha-v2",
        "/s/renamed-to.md": "sha-r",
        "/s/same.md": "sha-s",
    }
    old = {
        "/s/changed.md": _entry("sha-v1"),
        "/s/renamed-from.md": _entry("sha-r"),
        "/s/same.md": _entry("sha-s"),
        "/s/gone.md": _entry("sha-g"),
    }
    plan = core_sync.plan_sync(current, old)
    by_path = {c.path: c for c in plan}
    assert by_path["/s/added.md"].change == "added"
    assert by_path["/s/changed.md"].change == "updated"
    assert by_path["/s/renamed-to.md"].change == "renamed"
    assert by_path["/s/renamed-to.md"].old_path == "/s/renamed-from.md"
    assert by_path["/s/gone.md"].change == "removed"
    assert by_path["/s/same.md"].change == "unchanged"
    # ADD-before-DELETE: added < updated < renamed < removed < unchanged.
    order = [c.change for c in plan]
    assert order == ["added", "updated", "renamed", "removed", "unchanged"]


def test_plan_sync_ambiguous_rename_pairs_one():
    """Two same-hash arrivals for one departure: one rename + one add."""
    current = {"/s/y.md": "s1", "/s/z.md": "s1"}
    old = {"/s/x.md": _entry("s1")}
    plan = core_sync.plan_sync(current, old)
    changes = sorted(c.change for c in plan)
    assert changes == ["added", "renamed"]


def test_scoped_sources_limits_deletions_to_given_roots():
    state = {
        "version": 1,
        "incomplete": False,
        "sources": {
            "/a/keep.md": _entry("s1"),
            "/b/other.md": _entry("s2"),
            "/a/sub/deep.md": _entry("s3"),
        },
    }
    scoped = core_sync.scoped_sources(state, ["/a"])
    assert sorted(scoped) == ["/a/keep.md", "/a/sub/deep.md"]


def test_load_sync_state_blank_and_corrupt(tmp_path):
    blank = core_sync.load_sync_state(Bundle(tmp_path / "kb"))
    assert blank == {
        "version": 1,
        "incomplete": False,
        "sources": {},
        "permanent_failures": {},
    }

    state_path = core_sync.sync_state_path(Bundle(tmp_path / "kb"))
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("{oops", encoding="utf-8")
    recovered = core_sync.load_sync_state(Bundle(tmp_path / "kb"))
    assert recovered["incomplete"] is True  # flagged so resume logic kicks in
    assert recovered["sources"] == {}


def test_save_sync_state_atomic_and_confined(tmp_path):
    target = Bundle(tmp_path / "kb")
    state = {
        "version": 1,
        "incomplete": False,
        "sources": {},
        "permanent_failures": {},
    }
    core_sync.save_sync_state(target, state)
    leftovers = [
        p
        for p in (tmp_path / "kb" / ".okfsmith").iterdir()
        if p.name.endswith(".tmp")
    ]
    assert leftovers == []
    assert json.loads(
        core_sync.sync_state_path(target).read_text(encoding="utf-8")
    ) == state


def test_concepts_from_source_matches_resource(tmp_path):
    bundle = tmp_path / "kb"
    runner.invoke(app, ["init", str(bundle)], env=WIDE)
    target = Bundle.load(bundle)
    target.write_concept(
        "t/c",
        {"type": "Note", "title": "C", "resource": "/s/a.md"},
        "body",
    )
    target.write_concept(
        "t/d",
        {"type": "Note", "title": "D", "resource": "/s/b.md"},
        "body",
    )
    assert core_sync.concepts_from_source(target, "/s/a.md") == ["t/c"]


def test_remove_concepts_ignores_missing_and_returns_removed(tmp_path):
    bundle = tmp_path / "kb"
    runner.invoke(app, ["init", str(bundle)], env=WIDE)
    target = Bundle.load(bundle)
    target.write_concept("t/c", {"type": "Note", "title": "C"}, "body")
    assert core_sync.remove_concepts(target, ["t/c", "t/nope"]) == ["t/c"]
    assert core_sync.concepts_from_source(target, "/s/a.md") == []


# ===========================================================================
# Unit tests: Bundle.delete_concept
# ===========================================================================


def test_delete_concept_removes_and_unregisters(tmp_path):
    bundle = tmp_path / "kb"
    runner.invoke(app, ["init", str(bundle)], env=WIDE)
    target = Bundle.load(bundle)
    concept = target.write_concept("t/c", {"type": "Note", "title": "C"}, "body")
    assert target.delete_concept("t/c") is True
    assert not concept.path.exists()
    assert target.get("t/c") is None
    assert target.delete_concept("t/c") is False  # idempotent
    assert target.delete_concept("nope/none") is False


def test_delete_concept_confined_to_bundle(tmp_path):
    bundle = tmp_path / "kb"
    runner.invoke(app, ["init", str(bundle)], env=WIDE)
    target = Bundle.load(bundle)
    target.write_concept("t/c", {"type": "Note", "title": "C"}, "body")
    outside = tmp_path / "outside.txt"
    outside.write_text("precious", encoding="utf-8")
    # Tamper the in-memory path to point outside the bundle root.
    target._concepts["t/c"].path = outside
    assert target.delete_concept("t/c") is False
    assert outside.read_text(encoding="utf-8") == "precious"


# ===========================================================================
# Unit tests: dedup.unrecord_digest
# ===========================================================================


def test_unrecord_digest(tmp_path):
    bundle = tmp_path / "kb"
    runner.invoke(app, ["init", str(bundle)], env=WIDE)
    target = Bundle.load(bundle)
    src = tmp_path / "f.txt"
    src.write_text("x" * 64, encoding="utf-8")

    digest = "0" * 64
    dedup_mod.record_ingested(target, digest, str(src))
    assert dedup_mod.already_ingested(target, digest) is True
    assert dedup_mod.unrecord_digest(target, digest) is True
    assert dedup_mod.unrecord_digest(target, digest) is False  # idempotent
    # After unrecording, a fresh ingest no longer claims "already ingested".
    assert dedup_mod.already_ingested(target, digest) is False


# ===========================================================================
# Regression tests: reviewer-1 findings on the sync feature (fix commit)
# ===========================================================================


def _sync_quiet(bundle: Path, *args: str):
    return runner.invoke(
        app, ["sync", str(bundle), *args, "--no-llm", "--quiet"], env=WIDE
    )


# --- Finding 1: symlinked sources are skipped, never followed ----------------


def test_sync_skips_symlinked_source_file(tmp_path):
    """A symlink inside the source dir must not ingest outside content."""
    bundle = tmp_path / "kb"
    src = tmp_path / "src"
    src.mkdir()
    outside = tmp_path / "outside-secret.md"
    _doc(outside, "Secret", "topsecret-plans")
    _doc(src / "real.md", "Real", "realcontent")
    (src / "evil-link.md").symlink_to(outside)
    runner.invoke(app, ["init", str(bundle)], env=WIDE)

    result = _sync_quiet(bundle, str(src))
    assert result.exit_code == 0, result.output
    assert "1 added" in result.output
    assert "1 skipped" in result.output
    # The outside file's content was NOT ingested.
    assert _concept_ids(bundle) == ["real/real"]
    saved = _state(bundle)
    assert list(saved["sources"]) == [str((src / "real.md").resolve())]


def test_sync_symlink_skip_row_names_the_reason(tmp_path):
    bundle = tmp_path / "kb"
    src = tmp_path / "src"
    src.mkdir()
    target = _doc(src / "real.md", "Real", "realcontent")
    (src / "link.md").symlink_to(target)  # even an in-dir link is skipped
    runner.invoke(app, ["init", str(bundle)], env=WIDE)

    result = runner.invoke(
        app,
        ["sync", str(bundle), str(src), "--no-llm", "--format", "json"],
        env=WIDE,
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    rows = {f["path"]: f for f in payload["files"]}
    assert rows[str(src / "link.md")]["change"] == "skipped"
    assert "symlink" in rows[str(src / "link.md")]["detail"]
    assert payload["summary"]["skipped"] == 1


def test_sync_symlinked_source_dir_skipped(tmp_path):
    bundle = tmp_path / "kb"
    src = tmp_path / "src"
    src.mkdir()
    _doc(src / "real.md", "Real", "realcontent")
    runner.invoke(app, ["init", str(bundle)], env=WIDE)

    linkdir = tmp_path / "srcdir-link"
    linkdir.symlink_to(src, target_is_directory=True)
    result = _sync_quiet(bundle, str(linkdir))
    assert result.exit_code == 0, result.output
    assert "1 skipped" in result.output
    assert "0 added" in result.output
    assert _concept_ids(bundle) == []


# --- Finding 2: updater's entry records only its own new concepts -----------


def test_sync_update_then_delete_twin_releases_stale_concepts(tmp_path):
    """orig+twin identical; update orig; delete twin -> no stale concepts."""
    bundle = tmp_path / "kb"
    src = tmp_path / "src"
    src.mkdir()
    orig = _doc(src / "orig.md", "Orig", "sharedcontent")
    (src / "twin.md").write_bytes(orig.read_bytes())
    runner.invoke(app, ["init", str(bundle)], env=WIDE)
    assert _sync_quiet(bundle, str(src)).exit_code == 0
    assert _concept_ids(bundle) == ["orig/orig"]

    # Update orig: new content mints -2 ids; shared originals stay (twin).
    orig.write_text(orig.read_text(encoding="utf-8") + "\n\nNew stuff. " * 200,
                    encoding="utf-8")
    result = _sync_quiet(bundle, str(src))
    assert result.exit_code == 0, result.output
    assert "1 updated" in result.output
    assert _concept_ids(bundle) == ["orig/orig", "orig/orig-2"]
    # The updater's entry must NOT have swept the shared originals in.
    saved = _state(bundle)
    assert saved["sources"][str(orig.resolve())]["concepts"] == ["orig/orig-2"]

    # Deleting the twin drops the refcount -> stale originals are deleted.
    (src / "twin.md").unlink()
    result = _sync_quiet(bundle, str(src))
    assert result.exit_code == 0, result.output
    assert "1 removed" in result.output
    assert _concept_ids(bundle) == ["orig/orig-2"]


def test_concept_owners_lists_all_referencing_entries():
    state = {
        "sources": {
            "/s/a.md": _entry("d1", ("c/1", "c/2")),
            "/s/b.md": _entry("d1", ("c/1",)),
        }
    }
    assert core_sync.concept_owners(state, "c/1") == ["/s/a.md", "/s/b.md"]
    assert core_sync.concept_owners(state, "c/2") == ["/s/a.md"]
    assert core_sync.concept_owners(state, "c/nope") == []


# --- Finding 3: digest kept while other entries still reference it -----------


def test_sync_update_keeps_digest_while_shared(tmp_path):
    import hashlib

    bundle = tmp_path / "kb"
    src = tmp_path / "src"
    src.mkdir()
    orig = _doc(src / "orig.md", "Orig", "sharedcontent")
    (src / "twin.md").write_bytes(orig.read_bytes())
    runner.invoke(app, ["init", str(bundle)], env=WIDE)
    assert _sync_quiet(bundle, str(src)).exit_code == 0

    digest = hashlib.sha256(orig.read_bytes()).hexdigest()
    target = Bundle.load(bundle)
    assert digest in dedup_mod.load_manifest(target)

    # Updating the recorded path must NOT drop the digest while twin.md
    # still references it — otherwise a later ingest would duplicate.
    orig.write_text(orig.read_text(encoding="utf-8") + "\n\nNew stuff. " * 200,
                    encoding="utf-8")
    assert _sync_quiet(bundle, str(src)).exit_code == 0
    assert digest in dedup_mod.load_manifest(Bundle.load(bundle))
    assert dedup_mod.already_ingested(Bundle.load(bundle), digest) is True


# --- Finding 4: the bundle directory is never scanned as a source ------------


def test_sync_excludes_bundle_dir_from_scan(tmp_path):
    bundle = tmp_path / "src" / "kb"  # bundle INSIDE the source tree
    src = tmp_path / "src"
    src.mkdir(parents=True)
    _doc(src / "a.md", "A", "realcontent")
    runner.invoke(app, ["init", str(bundle)], env=WIDE)
    assert _sync_quiet(bundle, str(src)).exit_code == 0
    before = _concept_ids(bundle)

    result = runner.invoke(
        app, ["sync", str(bundle), str(src), "--no-llm", "--recursive"], env=WIDE
    )
    assert result.exit_code == 0, result.output
    assert "0 added" in result.output
    assert "never scanned as a source" in result.output
    # The bundle's own concept files were not ingested as sources.
    assert _concept_ids(bundle) == before

    # And the next run is stable (no accumulating garbage).
    again = _sync_quiet(bundle, str(src), "--recursive")
    assert again.exit_code == 0, again.output
    assert "0 added" in again.output
    assert _concept_ids(bundle) == before


# --- Finding 5: symlinked state path is refused -------------------------------


def test_sync_refuses_symlinked_state_dir(tmp_path):
    bundle = tmp_path / "kb"
    src = tmp_path / "src"
    src.mkdir()
    _doc(src / "a.md", "A", "realcontent")
    runner.invoke(app, ["init", str(bundle)], env=WIDE)
    assert _sync_quiet(bundle, str(src)).exit_code == 0

    outside = tmp_path / "evil-target"
    outside.mkdir()
    dotdir = bundle / ".okfsmith"
    for child in dotdir.iterdir():
        child.unlink()
    dotdir.rmdir()
    dotdir.symlink_to(outside)

    result = _sync_quiet(bundle, str(src))
    assert result.exit_code != 0
    assert "error [sync-refused]" in result.output
    assert "Traceback" not in result.output
    # Nothing was written through the symlink.
    assert list(outside.iterdir()) == []


def test_save_sync_state_refuses_symlinked_statedir(tmp_path):
    bundle = tmp_path / "kb"
    bundle.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (bundle / ".okfsmith").symlink_to(outside, target_is_directory=True)
    with pytest.raises(core_sync.SyncStateSymlinkError):
        core_sync.save_sync_state(Bundle(bundle), core_sync._blank_state())
    assert list(outside.iterdir()) == []


# --- Finding 6: non-UTF-8 filenames round-trip -------------------------------


def test_sync_non_utf8_filename_is_idempotent(tmp_path):
    bundle = tmp_path / "kb"
    src = tmp_path / "src"
    src.mkdir()
    raw_name = os.fsdecode(os.fsencode(str(src)) + b"/bad-\xff.md")
    _doc(Path(raw_name), "Bad", "weirdname")
    runner.invoke(app, ["init", str(bundle)], env=WIDE)

    first = _sync_quiet(bundle, str(src))
    assert first.exit_code == 0, first.output
    assert "1 added" in first.output

    second = _sync_quiet(bundle, str(src))
    assert second.exit_code == 0, second.output
    # No phantom rename/add/remove on the second pass.
    assert "1 unchanged" in second.output
    assert "0 added" in second.output
    assert "0 renamed" in second.output
    assert "0 removed" in second.output

    # The raw (surrogate) key round-trips through the state file.
    saved = core_sync.load_sync_state(Bundle.load(bundle))
    assert raw_name in saved["sources"] or str(Path(raw_name).resolve()) in saved[
        "sources"
    ]


def test_state_key_encoding_round_trip():
    raw = "/s/bad-\udcff.md"  # lone surrogate, as from undecodable bytes
    encoded = core_sync._encode_key(raw)
    assert encoded != raw
    assert encoded.startswith("sync-key-b64:")
    assert core_sync._decode_key(encoded) == raw
    # Plain UTF-8 keys (incl. non-ASCII) pass through untouched.
    for plain in ["/s/a.md", "/s/caf\u00e9-\u65e5\u672c\u8a9e.md"]:
        assert core_sync._encode_key(plain) == plain
        assert core_sync._decode_key(plain) == plain
    # A real filename that merely starts with the prefix is not mangled.
    tricky = "sync-key-b64:not-base64!!"
    assert core_sync._decode_key(tricky) == tricky


# --- Finding 7: concurrent syncs ----------------------------------------------


def test_sync_lock_is_exclusive_and_released(tmp_path):
    target = Bundle(tmp_path / "kb")
    (tmp_path / "kb").mkdir()
    release = core_sync.acquire_sync_lock(target)
    lock_path = core_sync.sync_lock_path(target)
    assert lock_path.exists()
    with pytest.raises(core_sync.SyncLockedError):
        core_sync.acquire_sync_lock(target)
    release()
    assert not lock_path.exists()
    # Re-acquire works after release.
    release2 = core_sync.acquire_sync_lock(target)
    release2()


def test_sync_lock_stale_is_reclaimed(tmp_path):
    import time

    target = Bundle(tmp_path / "kb")
    (tmp_path / "kb").mkdir()
    lock_path = core_sync.sync_lock_path(target)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # Dead PID + ancient mtime: reclaimable.
    lock_path.write_text("2147483647\n", encoding="utf-8")
    old = time.time() - 7200
    os.utime(lock_path, (old, old))
    release = core_sync.acquire_sync_lock(target)
    release()
    assert not lock_path.exists()


def test_sync_second_concurrent_sync_is_clean_error(tmp_path):
    bundle = tmp_path / "kb"
    src = tmp_path / "src"
    src.mkdir()
    _doc(src / "a.md", "A", "realcontent")
    runner.invoke(app, ["init", str(bundle)], env=WIDE)

    target = Bundle.load(bundle)
    release = core_sync.acquire_sync_lock(target)
    try:
        result = _sync_quiet(bundle, str(src))
    finally:
        release()
    assert result.exit_code != 0
    assert "error [sync-locked]" in result.output
    assert "Traceback" not in result.output
    # No state was clobbered by the loser.
    assert not (bundle / ".okfsmith" / "sync-state.json").exists()


# --- Finding 8: watch --format json is JSONL ----------------------------------


def test_sync_watch_json_is_jsonl(tmp_path, capsys):
    """Each watch cycle emits exactly one single-line JSON object."""
    bundle = tmp_path / "kb"
    src = tmp_path / "src"
    src.mkdir()
    _doc(src / "a.md", "A", "realcontent")
    runner.invoke(app, ["init", str(bundle)], env=WIDE)

    stop = threading.Event()
    thread = threading.Thread(
        target=sync_mod.run_watch,
        kwargs={
            "bundle_path": bundle,
            "sources": [src],
            "config": sync_mod.SyncConfig(no_llm=True),
            "interval": 0.05,
            "output_format": "json",
            "quiet": True,
            "stop_event": stop,
            "max_cycles": 2,
        },
        daemon=True,
    )
    try:
        thread.start()
        thread.join(timeout=30)
        assert not thread.is_alive()
    finally:
        stop.set()
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert lines, "watch emitted no JSON lines"
    for line in lines:
        assert "\n" not in line
        payload = json.loads(line)  # one JSON doc per line, no concat
        assert set(payload) >= {"summary", "files", "resumed"}


# --- Finding 9: permanent failures don't nag ----------------------------------


def _docx_missing_extra(tmp_path: Path) -> Path | None:
    """A .docx source that fails with a missing-extra error, else None."""
    from okfsmith.parsers import parse_file

    probe = tmp_path / "probe.docx"
    probe.write_bytes(b"PK\x03\x04" + b"\x00" * 64)
    try:
        error = (parse_file(probe).meta or {}).get("error") or ""
    finally:
        probe.unlink(missing_ok=True)
    if "markitdown is not installed" in error.lower():
        return probe
    return None


def test_sync_permanent_failure_no_resume_nag(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    probe = _docx_missing_extra(tmp_path)
    if probe is None:
        pytest.skip("office extra installed: no permanent-failure path")
    docx = src / "report.docx"
    docx.write_bytes(b"PK\x03\x04" + b"\x00" * 200)
    bundle = tmp_path / "kb"
    runner.invoke(app, ["init", str(bundle)], env=WIDE)

    # Explicitly named: fails, but does not abort into a resume loop.
    first = runner.invoke(
        app, ["sync", str(bundle), str(docx), "--no-llm", "--quiet"], env=WIDE
    )
    assert first.exit_code != 0
    assert "Traceback" not in first.output
    assert "did not complete" not in first.output
    saved = _state(bundle)
    assert saved["incomplete"] is False
    assert str(docx.resolve()) in saved["permanent_failures"]

    second = runner.invoke(
        app, ["sync", str(bundle), str(docx), "--no-llm", "--quiet"], env=WIDE
    )
    assert second.exit_code != 0
    # Still reported every run, but without the resume nag.
    assert "1 failed" in second.output
    assert "did not complete" not in second.output
    assert "resuming" not in second.output

    # A good file alongside still syncs fine (exit 0, per-file failure).
    good = _doc(src / "good.md", "Good", "goodcontent")
    mixed = runner.invoke(
        app,
        ["sync", str(bundle), str(good), str(docx), "--no-llm", "--quiet"],
        env=WIDE,
    )
    assert mixed.exit_code == 0, mixed.output
    assert "1 added" in mixed.output
    assert "1 failed" in mixed.output
    assert "permanent" in mixed.output

    # Once the file is gone, the stale permanent mark is dropped.
    docx.unlink()
    gone = _sync_quiet(bundle, str(src))
    assert gone.exit_code == 0, gone.output
    assert _state(bundle)["permanent_failures"] == {}


# --- Finding 10: docs nits -----------------------------------------------------


def test_docs_syncing_path_and_symlink_wording():
    repo = Path(__file__).resolve().parent.parent
    changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    # The guide lives at docs/src/syncing.md (built to docs/syncing.html).
    assert "docs/src/syncing.md" in changelog
    assert "docs/syncing.md" not in changelog.replace("docs/src/syncing.md", "")
    guide = (repo / "docs" / "src" / "syncing.md").read_text(encoding="utf-8")
    assert "symlink" in guide.lower()
    assert "JSONL" in guide or "jsonl" in guide.lower()


def test_sync_format_help_mentions_jsonl():
    result = runner.invoke(app, ["sync", "--help"], env=WIDE)
    assert result.exit_code == 0, result.output
    assert "JSONL" in result.output


# --- Finding A (re-verification): dedup donor misattribution --------------------


def _doc_text(title: str, seed: str, paras: int = 25) -> str:
    """Same generator as :func:`_doc`, but returns the text (for identical files)."""
    body = "".join(
        f"{seed} paragraph {i}: " + "lorem ipsum dolor sit amet. " * 12 + "\n\n"
        for i in range(paras)
    )
    text = f"# {title}\n\n{body}"
    assert len(text) > 1000
    return text


def _concept_body(bundle: Path, concept_id: str) -> str:
    for concept in Bundle.load(bundle).iter_concepts():
        if concept.id == concept_id:
            return concept.body
    raise AssertionError(f"concept {concept_id} not found")


def test_sync_stale_dedup_donor_is_verified_before_sharing(tmp_path):
    """A dedup-skipped file must share concepts with a source whose recorded
    sha256 matches its digest — never a stale manifest donor.

    Repro: a.md + b.md hold identical X -> sync; a.md is updated to Y ->
    sync; c.md is added holding the original X -> sync. The dedup manifest
    still names a.md for digest(X) even though a.md now holds Y, so c.md
    must resolve to b.md (recorded sha256 == X), not a.md.
    """
    bundle = tmp_path / "kb"
    src = tmp_path / "src"
    src.mkdir()
    assert runner.invoke(app, ["init", str(bundle)], env=WIDE).exit_code == 0

    text_x = _doc_text("Shared", "sharedseed")
    text_y = _doc_text("AlphaUpdated", "updatedseed")
    (src / "a.md").write_text(text_x, encoding="utf-8")
    (src / "b.md").write_text(text_x, encoding="utf-8")
    assert _sync(bundle, src).exit_code == 0

    (src / "a.md").write_text(text_y, encoding="utf-8")
    assert _sync(bundle, src).exit_code == 0

    (src / "c.md").write_text(text_x, encoding="utf-8")
    result = _sync(bundle, src)
    assert result.exit_code == 0, result.output

    saved = _state(bundle)
    a, b, c = (str(src / f"{name}.md") for name in "abc")
    assert saved["sources"][b]["sha256"] == saved["sources"][c]["sha256"]
    assert saved["sources"][a]["sha256"] != saved["sources"][b]["sha256"]
    # c.md (X content) shares the X-content concepts — b.md's, not a.md's Y.
    assert saved["sources"][c]["concepts"] == saved["sources"][b]["concepts"]
    assert set(saved["sources"][c]["concepts"]) != set(saved["sources"][a]["concepts"])
    body = _concept_body(bundle, saved["sources"][c]["concepts"][0])
    assert "sharedseed" in body and "updatedseed" not in body

    # Removing a.md releases the Y-content concepts: nothing may survive
    # pinned by c.md, which holds X.
    (src / "a.md").unlink()
    result = _sync(bundle, src)
    assert result.exit_code == 0, result.output
    remaining = {
        concept.id: _concept_body(bundle, concept.id)
        for concept in Bundle.load(bundle).iter_concepts()
    }
    assert not any("updatedseed" in text for text in remaining.values())
    assert any("sharedseed" in text for text in remaining.values())


def _fake_wiring(manifest: dict, on_unrecord: list):
    return sync_mod._Wiring(
        parse_file=None,
        sha256_of=None,
        already_ingested=None,
        record_ingested=None,
        unrecord_digest=lambda target, digest: on_unrecord.append(digest),
        load_manifest=lambda target: manifest,
        ingest_no_llm=None,
        sectioning=None,
    )


def test_donor_concepts_prefers_valid_sibling_over_stale_donor():
    """Manifest names a.md for the digest but a.md's recorded sha256 no
    longer matches: resolve to b.md, whose recorded sha256 does."""
    digest = "f" * 64
    state = {
        "sources": {
            "/src/a.md": {"sha256": "e" * 64, "concepts": ["a/y"]},
            "/src/b.md": {"sha256": digest, "concepts": ["a/x"]},
        }
    }
    wiring = _fake_wiring({digest: {"path": "/src/a.md"}}, [])
    change = core_sync.FileChange(path="/src/c.md", change="added", sha256=digest)
    assert sync_mod._donor_concepts(None, wiring, state, change) == ["a/x"]


def test_donor_concepts_trusts_valid_manifest_donor():
    """Manifest donor whose recorded sha256 still matches is used directly."""
    digest = "f" * 64
    state = {
        "sources": {
            "/src/a.md": {"sha256": digest, "concepts": ["a/x"]},
        }
    }
    unrecorded: list = []
    wiring = _fake_wiring({digest: {"path": "/src/a.md"}}, unrecorded)
    change = core_sync.FileChange(path="/src/c.md", change="added", sha256=digest)
    assert sync_mod._donor_concepts(None, wiring, state, change) == ["a/x"]
    assert unrecorded == []


def test_donor_concepts_rejects_stale_donor_with_no_valid_sibling():
    """No state source holds the digest: share nothing, and drop the stale
    manifest record so the file is ingested for real on the next pass."""
    digest = "f" * 64
    state = {
        "sources": {
            "/src/a.md": {"sha256": "e" * 64, "concepts": ["a/y"]},
        }
    }
    unrecorded: list = []
    wiring = _fake_wiring({digest: {"path": "/src/a.md"}}, unrecorded)
    change = core_sync.FileChange(path="/src/c.md", change="added", sha256=digest)
    assert sync_mod._donor_concepts(None, wiring, state, change) == []
    assert unrecorded == [digest]
