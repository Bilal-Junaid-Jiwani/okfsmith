"""Incremental sync state: change detection between source files and a bundle.

The sync state lives in ``<bundle>/.okfsmith/sync-state.json``::

    {"version": 1, "incomplete": false,
     "sources": {"<abs path>": {"sha256": "<hex>",
                                "concepts": ["<concept-id>", ...],
                                "size": 1234,
                                "mtime_ns": 123456789}, ...},
     "permanent_failures": {"<abs path>": {"reason": "...",
                                           "sha256": "<hex>"}, ...}}

State keys round-trip exactly, including non-UTF-8 filenames (stored as
``sync-key-b64:<base64>`` of the raw path bytes). A per-bundle lock file
``<bundle>/.okfsmith/sync.lock`` (``O_CREAT | O_EXCL``) serializes
concurrent syncs; stale locks (dead PID, or older than 10 minutes) are
reclaimed.

Reads never crash on a missing or corrupt state file (treated as empty, so
a damaged state degrades to a full re-scan, never a traceback). Writes are
atomic (temp file + ``os.replace``) so an interrupted sync can never leave
a half-written state behind; the ``incomplete`` flag marks a pass that
started but did not finish, letting the next run announce it is resuming.

No network calls; stdlib only.
"""

from __future__ import annotations

import base64
import contextlib
import json
import logging
import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from okfsmith.core.bundle import Bundle

log = logging.getLogger(__name__)

STATE_VERSION = 1
SYNC_STATE_FILENAME = "sync-state.json"
SYNC_LOCK_FILENAME = "sync.lock"

#: A lock older than this (or naming a dead PID) is treated as stale and
#: reclaimed by the next sync.
_LOCK_STALE_SECONDS = 600

#: Prefix marking a state key that could not be stored as plain UTF-8
#: (non-UTF-8 filenames); the remainder is base64 of the raw path bytes.
_NONUTF8_KEY_PREFIX = "sync-key-b64:"


class SyncStateSymlinkError(OSError):
    """A sync-state path component at/below the bundle root is a symlink; write refused.

    (A user-named symlinked *bundle directory* is not refused: ``Bundle``
    resolves it to its real path at startup, which is standard path
    resolution, not an attack. Only a symlinked ``.okfsmith/`` component
    is refused.)"""


class SyncLockedError(Exception):
    """Another sync pass currently holds the bundle's sync lock."""

# Processing order: additions and updates land before anything is deleted,
# so a rename (add new + delete old) never leaves a gap where queries fail.
_CHANGE_ORDER = ("added", "updated", "renamed", "removed", "unchanged")


@dataclass
class FileChange:
    """One planned change for a single source file."""

    path: str
    """Absolute source path (string form)."""

    change: str
    """One of ``added`` / ``updated`` / ``renamed`` / ``removed`` / ``unchanged``."""

    old_path: str | None = None
    """Previous path, for renames."""

    sha256: str | None = None
    """Current SHA-256 of the file (``None`` for removed files)."""

    old_sha256: str | None = None
    """SHA-256 recorded in the state (``None`` for added files)."""

    concepts: list[str] = field(default_factory=list)
    """Concept ids currently attributed to this source by the state."""


def sync_state_path(bundle: Bundle) -> Path:
    """Path of the sync-state file for *bundle* (not created by this call)."""
    from okfsmith.parsers.dedup import MANIFEST_DIRNAME

    return Path(bundle.root) / MANIFEST_DIRNAME / SYNC_STATE_FILENAME


def sync_lock_path(bundle: Bundle) -> Path:
    """Path of the per-bundle sync lock file (not created by this call)."""
    from okfsmith.parsers.dedup import MANIFEST_DIRNAME

    return Path(bundle.root) / MANIFEST_DIRNAME / SYNC_LOCK_FILENAME


def concept_owners(state: dict[str, Any], concept_id: str) -> list[str]:
    """State entries currently recording *concept_id* — its owner list.

    Shared concepts (identical files ingested twice hit ingest's content
    dedup) are owned by every entry that references them; a concept is only
    safe to delete when this list is empty.
    """
    return sorted(
        path
        for path, record in (state.get("sources") or {}).items()
        if concept_id in (record.get("concepts") or [])
    )


def _lock_is_stale(path: Path) -> bool:
    """Whether an existing lock file may be reclaimed.

    Stale = the owning PID is dead, or the lock is older than
    ``_LOCK_STALE_SECONDS``. Unreadable locks fall back to the age check.
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
        return True
    except OSError:
        return age > _LOCK_STALE_SECONDS  # cannot signal: age decides
    return age > _LOCK_STALE_SECONDS


def acquire_sync_lock(bundle: Bundle) -> Callable[[], None]:
    """Create the per-bundle sync lock; return a releaser callable.

    The lock file is created with ``O_CREAT | O_EXCL`` (stdlib only, no new
    dependencies), so two concurrent syncs cannot both hold it — the loser
    gets :class:`SyncLockedError`. Stale locks (dead PID or older than 10
    minutes) are reclaimed. The releaser only removes the lock when it still
    names our own PID, and never raises.

    Raises :class:`SyncStateSymlinkError` when the state dir is a symlink
    (same C1 refusal as the state write itself).
    """
    _refuse_symlinked_state_path(bundle)
    path = sync_lock_path(bundle)
    path.parent.mkdir(parents=True, exist_ok=True)
    _refuse_symlinked_state_path(bundle)  # TOCTOU backstop after mkdir
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        if _lock_is_stale(path):
            with contextlib.suppress(OSError):
                path.unlink()
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                raise SyncLockedError(
                    f"another sync is already running for this bundle "
                    f"(lock: {path})"
                ) from None
        else:
            raise SyncLockedError(
                f"another sync is already running for this bundle "
                f"(lock: {path})"
            ) from None
    try:
        handle = os.fdopen(fd, "w", encoding="utf-8")
    except OSError:
        os.close(fd)
        raise
    try:
        with handle:
            handle.write(f"{os.getpid()}\n")
    except OSError:
        with contextlib.suppress(OSError):
            path.unlink()
        raise

    def release() -> None:
        try:
            tag = path.read_text(encoding="utf-8").strip().split()[0]
        except (OSError, ValueError, IndexError):
            return
        if tag == str(os.getpid()):
            with contextlib.suppress(OSError):
                path.unlink()

    return release


def _blank_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "incomplete": False,
        "sources": {},
        "permanent_failures": {},
    }


def load_sync_state(bundle: Bundle) -> dict[str, Any]:
    """Load the sync state; ``{}``-equivalent blank state when absent/corrupt.

    A corrupt file is treated as empty (full re-scan on the next pass) and
    flagged ``incomplete`` so the caller announces the resume. Never raises
    for I/O or JSON problems.
    """
    path = sync_state_path(bundle)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _blank_state()
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        log.warning("ignoring corrupt sync state %s: %s", path, exc)
        blank = _blank_state()
        blank["incomplete"] = True
        return blank
    if not isinstance(data, dict):
        log.warning("ignoring corrupt sync state %s: not a JSON object", path)
        blank = _blank_state()
        blank["incomplete"] = True
        return blank
    sources = data.get("sources")
    if not isinstance(sources, dict):
        sources = {}
    # Keep only well-formed string-keyed records; drop anything else rather
    # than crashing on a hand-edited file.
    clean = {
        _decode_key(str(k)): v
        for k, v in sources.items()
        if isinstance(v, dict)
    }
    failures = data.get("permanent_failures")
    if not isinstance(failures, dict):
        failures = {}
    return {
        "version": data.get("version", STATE_VERSION),
        "incomplete": bool(data.get("incomplete", False)),
        "sources": clean,
        "permanent_failures": {
            str(k): v for k, v in failures.items() if isinstance(v, dict)
        },
    }


def _encode_key(value: str) -> str:
    """Encode a state key reversibly (finding: non-UTF-8 filenames).

    Keys that encode as plain UTF-8 pass through untouched (human-readable,
    stable for every existing state file). Keys containing surrogates
    (undecodable filename bytes) become ``sync-key-b64:<base64>`` of the raw
    bytes via surrogateescape. :func:`_decode_key` reverses it exactly, so a
    second sync sees the same key — no phantom renames.
    """
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raw = value.encode("utf-8", errors="surrogateescape")
        return _NONUTF8_KEY_PREFIX + base64.b64encode(raw).decode("ascii")
    return value


def _decode_key(value: str) -> str:
    """Reverse :func:`_encode_key`; unknown shapes pass through unchanged."""
    if value.startswith(_NONUTF8_KEY_PREFIX):
        blob = value[len(_NONUTF8_KEY_PREFIX):]
        try:
            raw = base64.b64decode(blob, validate=True)
            decoded = raw.decode("utf-8", errors="surrogateescape")
        except ValueError:
            return value
        # Round-trip check: a real filename that merely *starts* with the
        # prefix must not be mangled.
        if _encode_key(decoded) == value:
            return decoded
    return value


def _refuse_symlinked_state_path(bundle: Bundle) -> None:
    """Refuse when a state-path component at/below the bundle root is a symlink.

    Audit-C1 pattern (mirrors ``indexlog._refuse_symlink``): only components
    at/below the bundle root are inspected — never the absolute prefix
    (on some platforms ``/tmp`` itself is a symlink, which must not break
    normal use). A user-named symlinked *bundle directory* is not refused:
    ``Bundle`` resolves it to its real path at startup, which is standard
    path resolution, not an attack; only a symlinked ``.okfsmith/``
    component (or the state file itself) is refused, so sync state can
    never be written outside the bundle.
    """
    from okfsmith.parsers.dedup import MANIFEST_DIRNAME

    root = Path(bundle.root)
    if root.is_symlink():
        raise SyncStateSymlinkError(
            f"refusing to write sync state: bundle directory is a symlink: {root}"
        )
    candidate = root
    for part in (MANIFEST_DIRNAME, SYNC_STATE_FILENAME):
        candidate = candidate / part
        if candidate.is_symlink():
            raise SyncStateSymlinkError(
                f"refusing to write sync state through symlink: {candidate}"
            )


def save_sync_state(bundle: Bundle, state: dict[str, Any]) -> None:
    """Write the sync state atomically (temp file + ``os.replace``).

    Creates ``<bundle>/.okfsmith/`` on demand. Refuses (with
    :class:`SyncStateSymlinkError`) when a component of the state path
    at/below the bundle root is a symlink, so state can never be written
    outside the bundle. (A symlinked bundle directory itself is resolved
    to its real path by ``Bundle`` at startup and is not refused.)
    Raises :exc:`OSError` on I/O failure so the caller can surface a
    clean ``error [io-error]``.
    """
    _refuse_symlinked_state_path(bundle)
    path = sync_state_path(bundle)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Post-mkdir re-check: best-effort TOCTOU backstop against a symlink
    # swapped in between the check and the write.
    _refuse_symlinked_state_path(bundle)
    payload = {
        "version": STATE_VERSION,
        "incomplete": bool(state.get("incomplete", False)),
        "sources": {
            _encode_key(str(k)): {
                "sha256": v.get("sha256"),
                "concepts": sorted(set(map(str, v.get("concepts") or []))),
                "size": v.get("size"),
                "mtime_ns": v.get("mtime_ns"),
            }
            for k, v in (state.get("sources") or {}).items()
            if isinstance(v, dict)
        },
        "permanent_failures": {
            str(k): {
                "reason": str(v.get("reason") or ""),
                "sha256": v.get("sha256"),
            }
            for k, v in (state.get("permanent_failures") or {}).items()
            if isinstance(v, dict)
        },
    }
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    # Same-dir temp file + os.replace: readers never see a partial write,
    # and os.replace never follows a symlink at the destination.
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=SYNC_STATE_FILENAME + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp_name, path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def scoped_sources(state: dict[str, Any], roots: list[str]) -> dict[str, dict]:
    """State entries under any of *roots* (absolute path strings).

    Deletions are only ever considered for files under the roots scanned in
    the current invocation: syncing ``dirB`` must not delete concepts that
    came from ``dirA``.
    """
    resolved_roots = [Path(r) for r in roots]
    scoped: dict[str, dict] = {}
    for path_str, record in (state.get("sources") or {}).items():
        candidate = Path(path_str)
        for root in resolved_roots:
            if candidate == root or root in candidate.parents:
                scoped[path_str] = record
                break
    return scoped


def plan_sync(
    current: dict[str, str], old: dict[str, dict]
) -> list[FileChange]:
    """Classify *current* ``{path: sha256}`` against *old* state records.

    Returns changes in processing order — added, updated, renamed, removed,
    then unchanged — so the caller naturally honors ADD-before-DELETE.
    Renames are detected by content hash (same SHA-256, different path) and
    paired deterministically (sorted order); ambiguous leftovers fall back
    to plain added/removed.
    """
    old_paths = set(old)
    cur_paths = set(current)

    # Rename pairing: a disappeared path and an appeared path sharing a
    # SHA-256 is a rename, not a delete+create.
    vanished = sorted(old_paths - cur_paths)
    appeared = sorted(cur_paths - old_paths)
    by_sha: dict[str, list[str]] = {}
    for path in vanished:
        sha = old[path].get("sha256")
        if sha:
            by_sha.setdefault(sha, []).append(path)
    renames: list[tuple[str, str]] = []  # (old_path, new_path)
    renamed_old: set[str] = set()
    renamed_new: set[str] = set()
    for new_path in appeared:
        candidates = by_sha.get(current[new_path], [])
        if candidates:
            old_path = candidates.pop(0)
            renames.append((old_path, new_path))
            renamed_old.add(old_path)
            renamed_new.add(new_path)

    changes: list[FileChange] = []
    for path in sorted(cur_paths - old_paths - renamed_new):
        changes.append(
            FileChange(path=path, change="added", sha256=current[path])
        )
    for path in sorted(cur_paths & old_paths):
        record = old[path]
        if current[path] == record.get("sha256"):
            change = "unchanged"
        else:
            change = "updated"
        changes.append(
            FileChange(
                path=path,
                change=change,
                sha256=current[path],
                old_sha256=record.get("sha256"),
                concepts=list(record.get("concepts") or []),
            )
        )
    for old_path, new_path in sorted(renames):
        record = old[old_path]
        changes.append(
            FileChange(
                path=new_path,
                change="renamed",
                old_path=old_path,
                sha256=current[new_path],
                old_sha256=record.get("sha256"),
                concepts=list(record.get("concepts") or []),
            )
        )
    for path in sorted(old_paths - cur_paths - renamed_old):
        record = old[path]
        changes.append(
            FileChange(
                path=path,
                change="removed",
                old_sha256=record.get("sha256"),
                concepts=list(record.get("concepts") or []),
            )
        )
    order = {name: i for i, name in enumerate(_CHANGE_ORDER)}
    changes.sort(key=lambda c: (order[c.change], c.path))
    return changes


def _same_source(resource: str, source_path: str) -> bool:
    """Whether a concept's ``resource`` frontmatter refers to *source_path*."""
    if resource == source_path:
        return True
    try:
        return Path(resource).resolve() == Path(source_path).resolve()
    except OSError:
        return False


def concepts_from_source(bundle: Bundle, source_path: str) -> list[str]:
    """Concept ids whose frontmatter ``resource`` points at *source_path*.

    Used to adopt concepts after an interrupted sync (state lost but concepts
    present) and as a fallback when the state lists no concept ids. Sorted
    for deterministic output.
    """
    found: list[str] = []
    for concept in bundle.iter_concepts():
        resource = concept.frontmatter.get("resource")
        if isinstance(resource, str) and _same_source(resource, source_path):
            found.append(concept.id)
    return sorted(found)


def remove_concepts(bundle: Bundle, concept_ids: list[str]) -> list[str]:
    """Delete concepts by id (file removed, unregistered). Returns removed ids.

    Deletion is confined to the bundle root via
    :meth:`Bundle.delete_concept`; unknown or unremovable ids are skipped,
    never fatal.
    """
    removed: list[str] = []
    for concept_id in sorted(set(concept_ids)):
        if bundle.delete_concept(concept_id):
            removed.append(concept_id)
    return removed


__all__ = [
    "FileChange",
    "STATE_VERSION",
    "SYNC_LOCK_FILENAME",
    "SYNC_STATE_FILENAME",
    "SyncLockedError",
    "SyncStateSymlinkError",
    "acquire_sync_lock",
    "concept_owners",
    "concepts_from_source",
    "load_sync_state",
    "plan_sync",
    "remove_concepts",
    "save_sync_state",
    "scoped_sources",
    "sync_lock_path",
    "sync_state_path",
]
