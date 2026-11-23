"""Source-digest manifest for dedup.

Tracks which source files have already been ingested in
``<bundle>/.okfsmith/manifest.json``::

    {"sources": {"<sha256>": {"path": "...", "ingested_at": "..."}, ...}}

Helpers here create the directory/file on demand; reads never crash on a
missing or corrupt manifest (treated as empty).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path

log = logging.getLogger(__name__)

MANIFEST_DIRNAME = ".okfsmith"
MANIFEST_FILENAME = "manifest.json"
MANIFEST_LOCK_FILENAME = "manifest.lock"

# The manifest critical section is a load + tiny dict update + write of a
# small JSON file — milliseconds. A lock file older than this whose owner
# cannot be identified is garbage, not a live holder.
_LOCK_STALE_SECONDS = 60
# How long a writer waits for the cross-process manifest lock before
# degrading to the in-process lock alone (with a warning). A live holder
# releases in milliseconds, so reaching this means something is deeply
# stuck; failing the ingest would be worse than a small lost-update risk.
_LOCK_TIMEOUT_SECONDS = 30.0


def sha256_of(path: str | Path) -> str:
    """Hex SHA-256 digest of a file, streamed (no full read into memory)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_path(bundle) -> Path:
    """Path of the manifest file for *bundle* (not created by this call)."""
    return Path(bundle.root) / MANIFEST_DIRNAME / MANIFEST_FILENAME


def load_manifest(bundle) -> dict:
    """Load the manifest mapping digest -> record; {} when absent/corrupt."""
    mp = manifest_path(bundle)
    try:
        data = json.loads(mp.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        if not isinstance(exc, FileNotFoundError):
            log.warning("ignoring corrupt manifest %s: %s", mp, exc)
        return {}
    if not isinstance(data, dict):
        return {}
    sources = data.get("sources")
    return sources if isinstance(sources, dict) else {}


_thread_locks: dict[str, threading.Lock] = {}
_thread_locks_guard = threading.Lock()


def _thread_lock_for(key: str) -> threading.Lock:
    with _thread_locks_guard:
        lock = _thread_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _thread_locks[key] = lock
        return lock


def _manifest_lock_is_stale(path: Path) -> bool:
    """Whether an existing manifest lock file may be reclaimed.

    Same rule as the sync lock (core/sync.py): a lock naming a **live**
    PID is never stale. A lock naming a dead PID is reclaimable at once —
    manifest critical sections are milliseconds long, so no age grace is
    needed (PID reuse inside that window would only re-open the small
    lost-update race, and the atomic write still prevents corruption).
    Unreadable locks fall back to an age check.
    """
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return True  # vanished between check and open: caller retries
    try:
        pid = int(path.read_text(encoding="utf-8").strip().split()[0])
    except (OSError, ValueError, IndexError):
        return age > _LOCK_STALE_SECONDS
    if pid == os.getpid():
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True  # dead PID: holder is gone
    except OSError:
        return age > _LOCK_STALE_SECONDS  # cannot signal: age decides
    return False  # PID alive: never steal


def _acquire_manifest_file_lock(path: Path) -> int | None:
    """Create the manifest lock file (``O_CREAT | O_EXCL``); return its fd.

    Spins briefly while a live holder works. Returns None when the wait
    times out — the caller then degrades to the in-process lock alone
    rather than failing the ingest (see _LOCK_TIMEOUT_SECONDS).
    """
    deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if _manifest_lock_is_stale(path):
                with contextlib.suppress(OSError):
                    path.unlink()
                continue
            if time.monotonic() >= deadline:
                log.warning(
                    "manifest lock %s still held after %.0fs; proceeding "
                    "under the in-process lock only",
                    path,
                    _LOCK_TIMEOUT_SECONDS,
                )
                return None
            time.sleep(0.01)
            continue
        try:
            os.write(fd, f"{os.getpid()}\n".encode())
        except OSError:
            os.close(fd)
            with contextlib.suppress(OSError):
                path.unlink()
            raise
        return fd


def _release_manifest_file_lock(path: Path, fd: int | None) -> None:
    """Release the manifest lock; only removes a file still naming our PID."""
    if fd is None:
        return
    with contextlib.suppress(OSError):
        os.close(fd)
    try:
        tag = path.read_text(encoding="utf-8").strip().split()[0]
    except (OSError, ValueError, IndexError):
        return
    if tag == str(os.getpid()):
        with contextlib.suppress(OSError):
            path.unlink()


@contextlib.contextmanager
def _manifest_lock(bundle) -> Iterator[None]:
    """Serialize manifest read-modify-write across threads and processes.

    Two layers, mirroring patterns already in this codebase: an in-process
    per-path ``threading.Lock`` (the dashboard's job pool ingests into one
    bundle from several threads) and an ``O_CREAT | O_EXCL`` lock file
    next to the manifest (a CLI ingest racing the dashboard), created and
    reclaimed with the same PID-staleness discipline as the sync lock in
    ``core/sync.py``. Readers never lock: writes are atomic (temp file +
    ``os.replace``), so ``load_manifest`` always sees a complete file.
    """
    mp = manifest_path(bundle)
    mp.parent.mkdir(parents=True, exist_ok=True)
    with _thread_lock_for(str(mp)):
        lock_path = mp.parent / MANIFEST_LOCK_FILENAME
        fd = _acquire_manifest_file_lock(lock_path)
        try:
            yield
        finally:
            _release_manifest_file_lock(lock_path, fd)


def _write_manifest(bundle, sources: dict) -> None:
    """Atomically replace the manifest with *sources* (temp + os.replace)."""
    mp = manifest_path(bundle)
    mp.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"sources": sources}, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        dir=str(mp.parent), prefix=MANIFEST_FILENAME + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp_name, mp)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def record_ingested(bundle, digest: str, source: str | Path) -> None:
    """Record *digest* as ingested (creates .okfsmith/ + manifest as needed).

    The load → mutate → write runs under the per-bundle manifest lock and
    the write is atomic: concurrent ingests (dashboard job pool, or CLI +
    dashboard) can no longer lose each other's records or tear the file.
    """
    from okfsmith.core.spec import utc_now_iso

    # M8: source paths may hold undecodable bytes (surrogate escapes); the
    # manifest is UTF-8 JSON, so sanitize instead of crashing on write_text.
    path_text = str(source).encode("utf-8", errors="backslashreplace").decode("utf-8")
    with _manifest_lock(bundle):
        sources = load_manifest(bundle)
        sources[digest] = {"path": path_text, "ingested_at": utc_now_iso()}
        _write_manifest(bundle, sources)


def already_ingested(bundle, digest: str) -> bool:
    """True when *digest* is recorded in the bundle's manifest."""
    return digest in load_manifest(bundle)


def unrecord_digest(bundle, digest: str) -> bool:
    """Forget a recorded *digest* (its concepts are gone); True when removed.

    Used by incremental sync when it deletes the concepts a digest was
    recorded for: leaving the record would make a later ``ingest`` report
    "already ingested" for content the bundle no longer contains. The write
    is atomic (temp file + ``os.replace``) and runs under the same
    per-bundle manifest lock as ``record_ingested``, so a concurrent
    record/unrecord pair cannot lose each other's updates either.
    """
    if digest not in load_manifest(bundle):
        return False  # no-op fast path: creates nothing on disk
    with _manifest_lock(bundle):
        sources = load_manifest(bundle)
        if digest not in sources:
            return False
        del sources[digest]
        _write_manifest(bundle, sources)
    return True


__all__ = [
    "sha256_of",
    "manifest_path",
    "load_manifest",
    "record_ingested",
    "already_ingested",
    "unrecord_digest",
    "MANIFEST_DIRNAME",
    "MANIFEST_FILENAME",
    "MANIFEST_LOCK_FILENAME",
]
