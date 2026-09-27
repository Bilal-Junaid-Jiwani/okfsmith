"""Incremental sync state: change detection between source files and a bundle.

The sync state lives in ``<bundle>/.okfsmith/sync-state.json``::

    {"version": 1, "incomplete": false,
     "sources": {"<abs path>": {"sha256": "<hex>",
                                "concepts": ["<concept-id>", ...],
                                "size": 1234,
                                "mtime_ns": 123456789}, ...}}

Reads never crash on a missing or corrupt state file (treated as empty, so
a damaged state degrades to a full re-scan, never a traceback). Writes are
atomic (temp file + ``os.replace``) so an interrupted sync can never leave
a half-written state behind; the ``incomplete`` flag marks a pass that
started but did not finish, letting the next run announce it is resuming.

No network calls; stdlib only.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from okfsmith.core.bundle import Bundle

log = logging.getLogger(__name__)

STATE_VERSION = 1
SYNC_STATE_FILENAME = "sync-state.json"

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


def _blank_state() -> dict[str, Any]:
    return {"version": STATE_VERSION, "incomplete": False, "sources": {}}


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
        str(k): v
        for k, v in sources.items()
        if isinstance(v, dict)
    }
    return {
        "version": data.get("version", STATE_VERSION),
        "incomplete": bool(data.get("incomplete", False)),
        "sources": clean,
    }


def _sanitize(value: str) -> str:
    """Make *value* safely encodable as UTF-8 JSON (M8-style paths)."""
    return value.encode("utf-8", errors="backslashreplace").decode("utf-8")


def save_sync_state(bundle: Bundle, state: dict[str, Any]) -> None:
    """Write the sync state atomically (temp file + ``os.replace``).

    Creates ``<bundle>/.okfsmith/`` on demand. Raises :exc:`OSError` on I/O
    failure so the caller can surface a clean ``error [io-error]``.
    """
    path = sync_state_path(bundle)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": STATE_VERSION,
        "incomplete": bool(state.get("incomplete", False)),
        "sources": {
            _sanitize(str(k)): {
                "sha256": v.get("sha256"),
                "concepts": sorted(set(map(str, v.get("concepts") or []))),
                "size": v.get("size"),
                "mtime_ns": v.get("mtime_ns"),
            }
            for k, v in (state.get("sources") or {}).items()
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
    "SYNC_STATE_FILENAME",
    "concepts_from_source",
    "load_sync_state",
    "plan_sync",
    "remove_concepts",
    "save_sync_state",
    "scoped_sources",
    "sync_state_path",
]
