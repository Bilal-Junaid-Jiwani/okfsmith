"""Regression tests for the 0.7.13 sync-lock hardening (external audit finding).

The per-bundle ``sync.lock`` used to be reclaimed on a blind age check, so a
second sync could steal the lock mid-run and corrupt the bundle. The fix
(``_lock_is_stale``): a lock naming a **live** PID is never stale, whatever
its age; reclaim needs a dead (or unreadable) PID *and* age > 10 minutes.

These tests pin that invariant at the unit level — they would have failed
before the fix. Also covers the releaser's own-PID guard, the
``touch_sync_lock`` heartbeat, and the symlinked state-dir refusal.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from okfsmith.cli.app import app
from okfsmith.core import Bundle
from okfsmith.core import sync as core_sync
from okfsmith.core.sync import SyncLockedError, SyncStateSymlinkError

runner = CliRunner()
WIDE = {"COLUMNS": "200"}

_LOCK_STALE_SECONDS = 600
_DEAD_PID = 2**30  # far above any real PID; os.kill(pid, 0) -> ProcessLookupError


def _init_bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "kb"
    result = runner.invoke(app, ["init", str(bundle)], env=WIDE)
    assert result.exit_code == 0, result.output
    return bundle


def _lock_file(bundle: Path) -> Path:
    return core_sync.sync_lock_path(Bundle.load(bundle))


def _write_lock(lock: Path, content: str, age_seconds: float = 0) -> None:
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(content, encoding="utf-8")
    if age_seconds:
        old = time.time() - age_seconds
        os.utime(lock, (old, old))


def test_live_pid_lock_is_never_stale(tmp_path):
    bundle = _init_bundle(tmp_path)
    lock = _lock_file(bundle)
    _write_lock(lock, f"{os.getpid()}\n", age_seconds=_LOCK_STALE_SECONDS * 3)
    # Three hours old, but the holder is alive: never stale.
    assert core_sync._lock_is_stale(lock) is False


def test_acquire_refuses_to_steal_live_lock(tmp_path):
    bundle = _init_bundle(tmp_path)
    lock = _lock_file(bundle)
    _write_lock(lock, f"{os.getpid()}\n", age_seconds=_LOCK_STALE_SECONDS * 3)
    with pytest.raises(SyncLockedError, match="already running"):
        core_sync.acquire_sync_lock(Bundle.load(bundle))
    # The live holder's lock is untouched.
    assert lock.read_text(encoding="utf-8").strip().split()[0] == str(os.getpid())


def test_acquire_reclaims_dead_pid_lock_once_old(tmp_path):
    bundle = _init_bundle(tmp_path)
    lock = _lock_file(bundle)
    _write_lock(lock, f"{_DEAD_PID}\n", age_seconds=_LOCK_STALE_SECONDS + 60)
    release = core_sync.acquire_sync_lock(Bundle.load(bundle))
    assert lock.read_text(encoding="utf-8").strip().split()[0] == str(os.getpid())
    release()
    assert not lock.exists()


def test_acquire_refuses_dead_pid_lock_while_fresh(tmp_path):
    bundle = _init_bundle(tmp_path)
    lock = _lock_file(bundle)
    _write_lock(lock, f"{_DEAD_PID}\n")  # fresh: not yet stale
    with pytest.raises(SyncLockedError, match="already running"):
        core_sync.acquire_sync_lock(Bundle.load(bundle))
    assert lock.read_text(encoding="utf-8").strip().split()[0] == str(_DEAD_PID)


def test_acquire_reclaims_unreadable_lock_once_old(tmp_path):
    bundle = _init_bundle(tmp_path)
    lock = _lock_file(bundle)
    _write_lock(lock, "not-a-pid\n", age_seconds=_LOCK_STALE_SECONDS + 60)
    release = core_sync.acquire_sync_lock(Bundle.load(bundle))
    assert lock.read_text(encoding="utf-8").strip().split()[0] == str(os.getpid())
    release()
    assert not lock.exists()


def test_acquire_refuses_unreadable_lock_while_fresh(tmp_path):
    bundle = _init_bundle(tmp_path)
    lock = _lock_file(bundle)
    _write_lock(lock, "not-a-pid\n")
    with pytest.raises(SyncLockedError, match="already running"):
        core_sync.acquire_sync_lock(Bundle.load(bundle))
    assert lock.read_text(encoding="utf-8").strip().split()[0] == "not-a-pid"


def test_release_removes_only_own_lock(tmp_path):
    bundle = _init_bundle(tmp_path)
    lock = _lock_file(bundle)
    release = core_sync.acquire_sync_lock(Bundle.load(bundle))
    # Someone else's lock replaced ours on disk (e.g. a stale file from a
    # crashed run after we reclaimed): release() must not delete it.
    _write_lock(lock, f"{_DEAD_PID}\n")
    release()
    assert lock.exists()
    assert lock.read_text(encoding="utf-8").strip().split()[0] == str(_DEAD_PID)


def test_release_without_lock_never_raises(tmp_path):
    bundle = _init_bundle(tmp_path)
    release = core_sync.acquire_sync_lock(Bundle.load(bundle))
    core_sync.sync_lock_path(Bundle.load(bundle)).unlink()
    release()  # vanished between acquire and release: must not raise


def test_touch_heartbeat_refreshes_own_lock(tmp_path):
    bundle = _init_bundle(tmp_path)
    lock = _lock_file(bundle)
    release = core_sync.acquire_sync_lock(Bundle.load(bundle))
    try:
        old = time.time() - _LOCK_STALE_SECONDS
        os.utime(lock, (old, old))
        core_sync.touch_sync_lock(Bundle.load(bundle))
        assert lock.stat().st_mtime > old + 1
    finally:
        release()


def test_touch_ignores_foreign_lock(tmp_path):
    bundle = _init_bundle(tmp_path)
    lock = _lock_file(bundle)
    release = core_sync.acquire_sync_lock(Bundle.load(bundle))
    try:
        _write_lock(lock, f"{_DEAD_PID}\n", age_seconds=_LOCK_STALE_SECONDS + 60)
        mtime_before = lock.stat().st_mtime
        core_sync.touch_sync_lock(Bundle.load(bundle))
        assert lock.stat().st_mtime == mtime_before
        assert lock.read_text(encoding="utf-8").strip().split()[0] == str(_DEAD_PID)
    finally:
        release()


def test_touch_without_lock_never_raises(tmp_path):
    bundle = _init_bundle(tmp_path)
    core_sync.touch_sync_lock(Bundle.load(bundle))  # no lock file: must not raise


def test_acquire_refuses_symlinked_state_dir(tmp_path):
    bundle = _init_bundle(tmp_path)
    state_dir = bundle / ".okfsmith"
    outside = tmp_path / "outside"
    outside.mkdir()
    if state_dir.exists() or state_dir.is_symlink():
        for child in state_dir.iterdir():
            child.unlink()
        state_dir.rmdir()
    state_dir.symlink_to(outside, target_is_directory=True)
    with pytest.raises(SyncStateSymlinkError):
        core_sync.acquire_sync_lock(Bundle.load(bundle))


def test_save_state_refuses_symlinked_state_dir(tmp_path):
    bundle = _init_bundle(tmp_path)
    state_dir = bundle / ".okfsmith"
    outside = tmp_path / "outside"
    outside.mkdir()
    if state_dir.exists() or state_dir.is_symlink():
        for child in state_dir.iterdir():
            child.unlink()
        state_dir.rmdir()
    state_dir.symlink_to(outside, target_is_directory=True)
    with pytest.raises(SyncStateSymlinkError):
        core_sync.save_sync_state(Bundle.load(bundle), {"version": 1})


def test_load_state_non_object_is_blank_and_incomplete(tmp_path):
    bundle = _init_bundle(tmp_path)
    target = Bundle.load(bundle)
    path = core_sync.sync_state_path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[1, 2]\n", encoding="utf-8")
    recovered = core_sync.load_sync_state(target)
    assert recovered["incomplete"] is True
    assert recovered["sources"] == {}


def test_load_state_non_dict_sources_and_failures(tmp_path):
    bundle = _init_bundle(tmp_path)
    target = Bundle.load(bundle)
    path = core_sync.sync_state_path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 1, "sources": "oops", "permanent_failures": "oops"}),
        encoding="utf-8",
    )
    recovered = core_sync.load_sync_state(target)
    assert recovered["incomplete"] is False
    assert recovered["sources"] == {}
    assert recovered["permanent_failures"] == {}


def test_save_state_failure_cleans_temp_and_raises(tmp_path, monkeypatch):
    bundle = _init_bundle(tmp_path)
    target = Bundle.load(bundle)
    state_dir = bundle / ".okfsmith"
    state_dir.mkdir(parents=True, exist_ok=True)

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        core_sync.save_sync_state(target, {"version": 1})
    assert [p for p in state_dir.iterdir() if p.suffix == ".tmp"] == []


def test_save_state_temp_cleanup_failure_still_raises(tmp_path, monkeypatch):
    bundle = _init_bundle(tmp_path)
    target = Bundle.load(bundle)
    (bundle / ".okfsmith").mkdir(parents=True, exist_ok=True)

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    monkeypatch.setattr(os, "unlink", boom)
    with pytest.raises(OSError, match="disk full"):
        core_sync.save_sync_state(target, {"version": 1})


def test_refuse_symlinked_bundle_root(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)

    class FakeBundle:
        root = str(link)

    with pytest.raises(SyncStateSymlinkError, match="bundle directory is a symlink"):
        core_sync._refuse_symlinked_state_path(FakeBundle())


def test_release_lock_is_directory_never_raises(tmp_path):
    bundle = _init_bundle(tmp_path)
    lock = _lock_file(bundle)
    release = core_sync.acquire_sync_lock(Bundle.load(bundle))
    lock.unlink()
    lock.mkdir()  # read_text now raises IsADirectoryError (an OSError)
    release()  # must not raise
    lock.rmdir()


def test_acquire_fdopen_failure_raises_without_hanging(tmp_path, monkeypatch):
    bundle = _init_bundle(tmp_path)

    def boom(*args, **kwargs):
        raise OSError("fdopen failed")

    monkeypatch.setattr(os, "fdopen", boom)
    with pytest.raises(OSError, match="fdopen failed"):
        core_sync.acquire_sync_lock(Bundle.load(bundle))


def test_lock_is_stale_undecidable_kill_defers_to_age(tmp_path, monkeypatch):
    bundle = _init_bundle(tmp_path)
    lock = _lock_file(bundle)
    _write_lock(lock, f"{_DEAD_PID}\n")

    def undecidable(pid, sig):
        raise OSError("EPERM: cannot signal")

    monkeypatch.setattr(os, "kill", undecidable)
    assert core_sync._lock_is_stale(lock) is False  # fresh: age decides
    old = time.time() - _LOCK_STALE_SECONDS - 60
    os.utime(lock, (old, old))
    assert core_sync._lock_is_stale(lock) is True  # old: reclaim


def test_same_source_resolve_failure_returns_false(tmp_path, monkeypatch):
    from pathlib import Path as _Path

    def boom(self, *args, **kwargs):
        raise OSError("resolve failed")

    monkeypatch.setattr(_Path, "resolve", boom)
    assert core_sync._same_source("/a.md", "/b.md") is False
