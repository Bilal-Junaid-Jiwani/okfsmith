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
        concept = target.write_concept(
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
    assert blank == {"version": 1, "incomplete": False, "sources": {}}

    state_path = core_sync.sync_state_path(Bundle(tmp_path / "kb"))
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("{oops", encoding="utf-8")
    recovered = core_sync.load_sync_state(Bundle(tmp_path / "kb"))
    assert recovered["incomplete"] is True  # flagged so resume logic kicks in
    assert recovered["sources"] == {}


def test_save_sync_state_atomic_and_confined(tmp_path):
    target = Bundle(tmp_path / "kb")
    state = {"version": 1, "incomplete": False, "sources": {}}
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
