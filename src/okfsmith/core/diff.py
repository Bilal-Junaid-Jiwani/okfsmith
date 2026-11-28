"""Bundle diff: added / removed / changed concepts, as structured data.

The MCP ``diff`` tool renders this same comparison as paged markdown and
the CLI ``okfsmith diff`` command renders it as text or JSON; the
computation lives here (pure core — no FastMCP, no Typer) so both surfaces
agree on what "changed" means.

Two modes, mirroring the MCP tool:

- ``diff_bundles`` — compare the bound bundle ("current") against another
  bundle directory ("previous"): added = ids only in current, removed =
  ids only in previous, changed = same id with a different body SHA-256
  (or a different title).
- ``diff_against_sync_state`` — compare against the ``sync-state.json``
  snapshot (``<bundle>/.okfsmith/sync-state.json``): added/removed come
  from the snapshot's recorded concept ids, and "changed" marks concepts
  whose recorded source file's current SHA-256 differs from the snapshot.

Trust rules (same as the MCP tool): sync-state manifest paths are
untrusted bundle input — only paths inside the bundle root are hashed or
echoed (bundle-relative); outside paths are counted as untrusted and
skipped with a marker, never hashed (no host-file SHA-256/existence
oracle) and never echoed. The ``against`` directory is pre-scanned
(bounded file count, must contain markdown concept files) so a
filesystem root can never trigger a full-disk walk.

Temporal replay: every row carries the concept's temporal status
(``current`` / ``superseded`` / ``expired`` / ``not_yet_valid``) evaluated
at ``as_of`` when one is given, at now otherwise. In ``against`` mode
removed rows are evaluated against the combined supersession graph of
both bundles, so a superseder that only exists in the current bundle
still counts; in sync-state mode a removed concept has no frontmatter on
file, so its row carries no status.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from okfsmith.core import temporal as _temporal
from okfsmith.core.bundle import Bundle, Concept

#: Cap for the pre-scan of a ``diff(against=...)`` directory: bounds the
#: filesystem walk so ``against="/"`` fails fast with a clean error
#: instead of crawling the whole disk.
DIFF_AGAINST_MAX_FILES = 5000


class DiffError(Exception):
    """An expected, user-facing diff failure with a stable error code."""

    def __init__(self, code: str, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


@dataclass
class DiffRow:
    """One added/removed concept: title/sha are ``None`` when unavailable.

    (Removed concepts in sync-state mode have no frontmatter or body left
    on disk, so neither a title nor a body SHA-256 exists for them.)
    """

    id: str
    title: str | None = None
    sha256: str | None = None
    temporal_status: str | None = None
    superseded_by: str | None = None


@dataclass
class ChangedRow:
    """One changed concept: old/new body SHA-256, plus the source file
    (bundle-relative) in sync-state mode, ``None`` in ``against`` mode."""

    id: str
    title: str | None = None
    old_sha256: str | None = None
    new_sha256: str | None = None
    source: str | None = None
    temporal_status: str | None = None
    superseded_by: str | None = None


@dataclass
class DiffResult:
    """The whole comparison: three sorted sections plus mode metadata."""

    mode: str  # "against" | "sync-state"
    against: str | None = None
    as_of: datetime | None = None
    added: list[DiffRow] = field(default_factory=list)
    removed: list[DiffRow] = field(default_factory=list)
    changed: list[ChangedRow] = field(default_factory=list)
    source_records: int = 0  # sync-state mode: manifest source records read
    untrusted: int = 0  # sync-state mode: skipped outside-root manifest entries

    def counts(self) -> dict[str, int]:
        """``{"added": n, "removed": n, "changed": n}`` for JSON output."""
        return {
            "added": len(self.added),
            "removed": len(self.removed),
            "changed": len(self.changed),
        }


def concept_sha256(concept: Concept) -> str:
    """Hex SHA-256 of the concept's markdown body; never raises."""
    try:
        return hashlib.sha256(concept.body.encode("utf-8")).hexdigest()
    except Exception:
        return "unavailable"


def concept_title(concept: Concept) -> str:
    """Frontmatter title, falling back to the concept id; never raises."""
    try:
        title = concept.frontmatter.get("title")
    except Exception:
        return concept.id
    if title is None:
        return concept.id
    return str(title).strip() or concept.id


def _sha256_file(path: Path) -> str | None:
    """Hex SHA-256 of a file's bytes (streamed); ``None`` on any I/O failure."""
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(65536), b""):
                digest.update(block)
        return digest.hexdigest()
    except (OSError, ValueError):
        return None


def _temporal_pair(
    index: _temporal.SupersessionIndex,
    concept: Concept,
    moment: datetime,
) -> tuple[str | None, str | None]:
    """``(status name, superseded_by)`` for *concept* at *moment*; never raises."""
    try:
        status = index.status(concept, moment)
        return status.name, status.superseded_by
    except Exception:
        return None, None


def validate_against_dir(other_root: Path) -> str | None:
    """Validate *other_root* as a diff comparison target.

    Returns an error string when the directory must not be walked,
    ``None`` when it is safe to hand to :func:`Bundle.load`. The scan is
    lazy and bails out past :data:`DIFF_AGAINST_MAX_FILES` total files
    ("too many files" error) instead of crawling huge trees; a directory
    with no markdown concept files at all is not a bundle (clean error).
    Never raises.
    """
    try:
        total = 0
        md = 0
        for _root, _dirs, files in os.walk(other_root):
            for name in files:
                total += 1
                if total > DIFF_AGAINST_MAX_FILES:
                    return (
                        "`against` has too many files "
                        f"(over {DIFF_AGAINST_MAX_FILES}) — pass a bundle "
                        "directory, not a filesystem root."
                    )
                if name.endswith((".md", ".markdown")):
                    md += 1
    except OSError as exc:
        return f"could not scan `against` directory {other_root!r}: {exc}."
    if md == 0:
        return (
            "`against` does not look like a bundle directory "
            f"(no markdown concept files found under {other_root!r})."
        )
    return None


def diff_bundles(
    current: Bundle,
    previous: Bundle,
    as_of: datetime | None = None,
) -> DiffResult:
    """Diff *current* against *previous*: added / removed / changed.

    ``as_of`` (``None`` = now) replays validity and supersession at that
    instant; removed rows are evaluated against the combined supersession
    graph of both bundles (current frontmatter wins on a shared id).
    Never raises for hostile frontmatter.
    """
    moment = as_of if as_of is not None else _temporal.utcnow()
    current_map = {c.id: c for c in current.iter_concepts()}
    previous_map = {c.id: c for c in previous.iter_concepts()}
    # The supersession graph spans both bundles: a removed concept's
    # superseder usually lives only in the current bundle, and the
    # current bundle's own index early-returns "current" for ids it does
    # not contain — so evaluate every row against the combined index
    # (current frontmatter wins on a shared id).
    combined = _temporal.SupersessionIndex(
        [(cid, c.frontmatter or {}) for cid, c in {**previous_map, **current_map}.items()]
    )

    def _row(concept: Concept) -> DiffRow:
        status, superseded_by = _temporal_pair(combined, concept, moment)
        return DiffRow(
            id=concept.id,
            title=concept_title(concept),
            sha256=concept_sha256(concept),
            temporal_status=status,
            superseded_by=superseded_by,
        )

    added = sorted(set(current_map) - set(previous_map))
    removed = sorted(set(previous_map) - set(current_map))
    changed_ids = sorted(
        cid
        for cid in set(current_map) & set(previous_map)
        if concept_sha256(current_map[cid]) != concept_sha256(previous_map[cid])
        or concept_title(current_map[cid]) != concept_title(previous_map[cid])
    )
    changed = []
    for cid in changed_ids:
        status, superseded_by = _temporal_pair(combined, current_map[cid], moment)
        changed.append(
            ChangedRow(
                id=cid,
                title=concept_title(current_map[cid]),
                old_sha256=concept_sha256(previous_map[cid]),
                new_sha256=concept_sha256(current_map[cid]),
                temporal_status=status,
                superseded_by=superseded_by,
            )
        )
    return DiffResult(
        mode="against",
        as_of=moment,
        added=[_row(current_map[cid]) for cid in added],
        removed=[_row(previous_map[cid]) for cid in removed],
        changed=changed,
    )


def _decode_state_key(key: Any) -> str:
    """Reverse the sync-state key encoding (``sync-key-b64:``); never raises."""
    prefix = "sync-key-b64:"
    if isinstance(key, str) and key.startswith(prefix):
        try:
            raw = base64.b64decode(key[len(prefix):].encode("ascii"))
            return raw.decode("utf-8", errors="replace")
        except (ValueError, binascii.Error, UnicodeError):
            return key
    return str(key)


def _manifest_relpath(bundle: Bundle, raw_path: Any) -> str | None:
    """Bundle-relative form of a sync-state manifest path, or ``None``.

    Manifest paths live in untrusted bundle input
    (``<bundle>/.okfsmith/sync-state.json``), so they are never trusted
    blindly: only paths that stay inside the bundle root come back (as a
    bundle-relative POSIX path, safe to echo). Absolute outside paths and
    ``..`` escapes return ``None``. The parent directory is resolved
    (catching escapes through a symlinked parent directory); the entry
    itself is never followed — a symlinked entry is rejected outright. The
    final path is then re-resolved so trailing ``..`` components normalize
    to the bundle root — or to an ancestor — instead of slipping past as a
    literal string; ``"."`` (the root itself) and any outside path return
    ``None``. Never raises.
    """
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    candidate = Path(raw_path.strip())
    if not candidate.is_absolute():
        candidate = bundle.root / candidate
    try:
        parent = candidate.parent.resolve()
        root = bundle.root
        if parent != root and root not in parent.parents:
            return None
        final = parent / candidate.name
        if final.is_symlink():
            return None
        resolved = final.resolve()
        if resolved != root and root not in resolved.parents:
            return None
        rel = resolved.relative_to(root).as_posix()
    except (OSError, RuntimeError, ValueError):
        return None
    return None if rel == "." else rel


def _load_sync_state_raw(bundle: Bundle) -> dict[str, Any] | None:
    """Read ``<bundle>/.okfsmith/sync-state.json``; ``None`` when unusable.

    Never raises: a missing file, a symlink (never followed — same rule as
    :meth:`Bundle.load`), invalid JSON, or a non-mapping payload all
    degrade to ``None``.
    """
    try:
        from okfsmith.core.sync import SYNC_STATE_FILENAME
        from okfsmith.parsers.dedup import MANIFEST_DIRNAME
    except ImportError:
        return None
    try:
        path = bundle.root / MANIFEST_DIRNAME / SYNC_STATE_FILENAME
        if path.is_symlink() or not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    return payload if isinstance(payload, dict) else None


def diff_against_sync_state(
    bundle: Bundle,
    as_of: datetime | None = None,
) -> DiffResult:
    """Diff *bundle* against its ``sync-state.json`` snapshot.

    Raises :class:`DiffError` (``no-snapshot``) when no usable snapshot
    exists — the caller should suggest ``--against`` or running ``sync``
    first. ``as_of`` (``None`` = now) replays validity and supersession at
    that instant for added/changed rows; removed rows carry no temporal
    status (the snapshot records ids only).
    """
    moment = as_of if as_of is not None else _temporal.utcnow()
    state = _load_sync_state_raw(bundle)
    if state is None:
        raise DiffError(
            "no-snapshot",
            "no `against` bundle directory given and no usable "
            "`sync-state.json` snapshot found in this bundle (looked for "
            "`<bundle>/.okfsmith/sync-state.json`).",
            "Pass `--against <path to a bundle directory>` to compare "
            "against it, or run `okfsmith sync` first to record a snapshot.",
        )
    # Manifest paths are untrusted bundle input: only paths inside the
    # bundle root are hashed or echoed (bundle-relative). Outside paths
    # are counted as untrusted and skipped with a marker — never hashed
    # (no host-file SHA-256/existence oracle) and never echoed verbatim.
    origins: dict[str, list[tuple[str, str | None]]] = {}
    records = state.get("sources")
    record_count = 0
    untrusted = 0
    if isinstance(records, dict):
        record_count = len(records)
        for key, record in records.items():
            if not isinstance(record, dict):
                continue
            rel = _manifest_relpath(bundle, _decode_state_key(key))
            if rel is None:
                untrusted += 1
                continue
            sha = record.get("sha256")
            sha = sha if isinstance(sha, str) else None
            raw_concepts = record.get("concepts")
            ids = (
                [str(cid) for cid in raw_concepts]
                if isinstance(raw_concepts, (list, tuple))
                else []
            )
            for cid in ids:
                origins.setdefault(cid, []).append((rel, sha))
    current_map = {c.id: c for c in bundle.iter_concepts()}
    index = _temporal.SupersessionIndex.from_bundle(bundle)
    prev_ids = set(origins)
    added = sorted(set(current_map) - prev_ids)
    removed = sorted(prev_ids - set(current_map))
    changed: list[ChangedRow] = []
    for cid in sorted(set(current_map) & prev_ids):
        for rel, old_sha in origins[cid]:
            if not old_sha:
                continue
            candidate = bundle.root / rel
            if candidate.is_symlink() or not candidate.is_file():
                continue
            new_sha = _sha256_file(candidate)
            if new_sha and new_sha != old_sha:
                status, superseded_by = _temporal_pair(
                    index, current_map[cid], moment
                )
                changed.append(
                    ChangedRow(
                        id=cid,
                        title=concept_title(current_map[cid]),
                        old_sha256=old_sha,
                        new_sha256=new_sha,
                        source=rel,
                        temporal_status=status,
                        superseded_by=superseded_by,
                    )
                )
                break

    def _row(concept: Concept) -> DiffRow:
        status, superseded_by = _temporal_pair(index, concept, moment)
        return DiffRow(
            id=concept.id,
            title=concept_title(concept),
            sha256=concept_sha256(concept),
            temporal_status=status,
            superseded_by=superseded_by,
        )

    return DiffResult(
        mode="sync-state",
        as_of=moment,
        added=[_row(current_map[cid]) for cid in added],
        removed=[
            DiffRow(id=cid) for cid in removed
        ],
        changed=changed,
        source_records=record_count,
        untrusted=untrusted,
    )
