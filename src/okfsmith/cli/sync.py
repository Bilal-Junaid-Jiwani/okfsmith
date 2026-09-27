"""Incremental sync engine: change detection, apply, and watch loop.

The Typer command lives in :mod:`okfsmith.cli.commands` (``okfsmith sync``);
this module holds the orchestration so it can be exercised without Typer.

Design notes:

- Change detection is SHA-256 per source file, recorded in
  ``<bundle>/.okfsmith/sync-state.json`` (see :mod:`okfsmith.core.sync`).
  The state file is not ``*.md``, so ``validate``/``list``/``search`` never
  see it.
- ADD-before-DELETE: the plan is applied in added → updated → renamed →
  removed order, so a rename (same content, new path) never leaves a gap.
- Concept ids may be shared by several state entries (identical files
  ingested twice hit ingest's content dedup). A concept is only deleted
  when no remaining state entry references it.
- Every mutating pass is idempotent: re-running it after an interruption
  converges on the same end state. The state file is saved atomically
  after every file operation, and an ``incomplete`` flag marks passes that
  did not finish so the next run can announce the resume.
"""

from __future__ import annotations

import importlib
import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from okfsmith.cli.commands import (
    CliError,
    _collect_inputs,
    _dump_json,
    _ingest_llm_one,
    _ingest_no_llm_one,
    _jsonable,
    _lazy_attr,
    _plural,
)
from okfsmith.core import Bundle, indexlog
from okfsmith.core import sync as _state

console = Console()

#: Outcome labels in the order they are summarized.
OUTCOME_ORDER = (
    "added",
    "updated",
    "renamed",
    "removed",
    "unchanged",
    "skipped",
    "failed",
)

_OUTCOME_STYLE = {
    "added": "green",
    "updated": "yellow",
    "renamed": "cyan",
    "removed": "red",
    "unchanged": "dim",
    "skipped": "yellow",
    "failed": "red",
}


@dataclass
class SyncConfig:
    """Options for a sync pass (mirrors the CLI flags)."""

    no_llm: bool = False
    recursive: bool = False
    dry_run: bool = False
    quiet: bool = False
    model: str | None = None
    provider: str | None = None
    api_base: str | None = None
    api_key: str | None = None


@dataclass
class FileResult:
    """Outcome for a single source file."""

    path: str
    change: str  # added|updated|renamed|removed|unchanged|skipped|failed
    concepts: int = 0
    detail: str = ""
    old_path: str | None = None


@dataclass
class SyncResult:
    """Outcome of one sync pass."""

    results: list[FileResult] = field(default_factory=list)
    resumed: bool = False
    dry_run: bool = False

    def summary(self) -> dict[str, int]:
        counts = dict.fromkeys(OUTCOME_ORDER, 0)
        for result in self.results:
            counts[result.change] = counts.get(result.change, 0) + 1
        return counts


@dataclass
class _Wiring:
    """Lazily-imported slice callables (mirrors the ingest command)."""

    parse_file: Any
    sha256_of: Any
    already_ingested: Any
    record_ingested: Any
    unrecord_digest: Any
    load_manifest: Any
    ingest_no_llm: Any
    sectioning: Any
    section: Any = None
    SectionInput: Any = None
    run: Any = None
    LLMUnavailableError: Any = None


def _wiring(no_llm: bool) -> _Wiring:
    parse_file = _lazy_attr("okfsmith.parsers", "parse_file")
    wiring = _Wiring(
        parse_file=parse_file,
        sha256_of=_lazy_attr("okfsmith.parsers.dedup", "sha256_of"),
        already_ingested=_lazy_attr("okfsmith.parsers.dedup", "already_ingested"),
        record_ingested=_lazy_attr("okfsmith.parsers.dedup", "record_ingested"),
        unrecord_digest=_lazy_attr("okfsmith.parsers.dedup", "unrecord_digest"),
        load_manifest=_lazy_attr("okfsmith.parsers.dedup", "load_manifest"),
        ingest_no_llm=_lazy_attr("okfsmith.parsers.ingest_no_llm", "ingest_no_llm"),
        sectioning=importlib.import_module("okfsmith.parsers.sectioning"),
    )
    if not no_llm:
        wiring.section = _lazy_attr("okfsmith.parsers.sectioning", "section")
        wiring.SectionInput = _lazy_attr("okfsmith.extract", "SectionInput")
        wiring.run = _lazy_attr("okfsmith.extract", "run")
        wiring.LLMUnavailableError = _lazy_attr(
            "okfsmith.extract", "LLMUnavailableError"
        )
    return wiring


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


@dataclass
class ScanResult:
    """Outcome of scanning the sources."""

    files: list[Path]
    """Scannable source files (resolved, de-duplicated)."""

    skipped: list[FileResult]
    """Per-file skip rows (symlinked sources are never followed)."""

    bundle_skipped: int = 0
    """Files skipped because they live inside the bundle directory."""


def _scan_files(
    sources: list[Path], recursive: bool, bundle_root: Path | None = None
) -> ScanResult:
    """Scan *sources*; symlinks and bundle-internal files are skipped.

    Reuses the ingest command's collector (reserved ``index.md``/``log.md``
    are never sources; FIFOs and friends fail cleanly via CliError).

    - Any source path that is itself a symlink is skipped with a per-file
      warning row — sync never follows symlinks, so outside content can
      never be ingested through one (and a resolved-outside path can never
      enter the state).
    - Files under *bundle_root* are skipped (a bundle is never its own
      source); the caller reports the count as a single note.
    """
    seen: dict[str, Path] = {}
    skipped: list[FileResult] = []
    bundle_skipped = 0
    bundle_real = os.path.realpath(bundle_root) if bundle_root is not None else None
    for source in sources:
        if source.is_symlink():
            # A symlinked source root is skipped outright (never descended).
            skipped.append(
                FileResult(
                    path=str(source),
                    change="skipped",
                    detail="skipped: source is a symlink "
                    "(sync never follows symlinks)",
                )
            )
            continue
        for path in _collect_inputs(source, recursive):
            if path.is_symlink():
                skipped.append(
                    FileResult(
                        path=str(path),
                        change="skipped",
                        detail="skipped: source is a symlink "
                        "(sync never follows symlinks)",
                    )
                )
                continue
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if bundle_real is not None:
                real = os.path.realpath(resolved)
                if real == bundle_real or real.startswith(bundle_real + os.sep):
                    bundle_skipped += 1
                    continue
            seen.setdefault(str(resolved), resolved)
    files = [seen[key] for key in sorted(seen)]
    return ScanResult(files=files, skipped=skipped, bundle_skipped=bundle_skipped)


def _hash_files(
    files: list[Path], wiring: _Wiring
) -> tuple[dict[str, str], list[FileResult]]:
    """SHA-256 per file; unreadable files become ``failed`` results, not aborts."""
    current: dict[str, str] = {}
    failed: list[FileResult] = []
    for path in files:
        key = str(path)
        try:
            current[key] = wiring.sha256_of(path)
        except Exception as exc:  # noqa: BLE001 — per-file failure, keep going
            failed.append(
                FileResult(path=key, change="failed", detail=f"cannot hash: {exc}")
            )
    return current, failed


def _display_path(path_str: str) -> str:
    """Path relative to the CWD when possible, else absolute."""
    try:
        return str(Path(path_str).relative_to(Path.cwd()))
    except ValueError:
        return path_str


# ---------------------------------------------------------------------------
# Concept bookkeeping
# ---------------------------------------------------------------------------


def _referenced_by_others(
    state: dict[str, Any], path: str
) -> set[str]:
    """Concept ids referenced by state entries other than *path*."""
    referenced: set[str] = set()
    for other, record in (state.get("sources") or {}).items():
        if other != path:
            referenced.update(record.get("concepts") or [])
    return referenced


def _owned_concepts(target: Bundle, state: dict[str, Any], path: str) -> list[str]:
    """Concept ids attributable to *path* and safe to delete.

    Union of the ids recorded in the state and the ids discovered via the
    ``resource`` frontmatter fallback (covers interrupted syncs where the
    state was lost but the concepts exist), minus ids still referenced by
    other state entries (shared ownership from identical files).
    """
    recorded = set((state.get("sources") or {}).get(path, {}).get("concepts") or [])
    recorded.update(_state.concepts_from_source(target, path))
    return sorted(recorded - _referenced_by_others(state, path))


def _save_state(target: Bundle, state: dict[str, Any]) -> None:
    """Persist the sync state, mapping a symlinked state path to CliError.

    :class:`core.sync.SyncStateSymlinkError` becomes a clean
    ``error [sync-refused]``; other I/O failures propagate as OSError for
    the caller's ``error [io-error]`` mapping.
    """
    try:
        _state.save_sync_state(target, state)
    except _state.SyncStateSymlinkError as exc:
        raise CliError(
            "sync-refused",
            str(exc),
            "Remove the symlink so '<bundle>/.okfsmith/' is a real "
            "directory inside the bundle, then retry.",
        ) from None


def _record_source(
    target: Bundle,
    state: dict[str, Any],
    path: str,
    sha256: str,
    concepts: list[str],
) -> None:
    """Update the state entry for *path* and persist it atomically."""
    try:
        stat = Path(path).stat()
        size, mtime_ns = stat.st_size, stat.st_mtime_ns
    except OSError:
        size, mtime_ns = None, None
    state.setdefault("sources", {})[path] = {
        "sha256": sha256,
        "concepts": sorted(set(concepts)),
        "size": size,
        "mtime_ns": mtime_ns,
    }
    # A source that now ingests cleanly is no longer a permanent failure.
    (state.get("permanent_failures") or {}).pop(path, None)
    _save_state(target, state)


def _record_permanent_failure(
    target: Bundle,
    state: dict[str, Any],
    change: _state.FileChange,
    exc: CliError,
) -> FileResult:
    """Record a never-retryable per-source failure without aborting the pass.

    A source that can never succeed without user action (e.g. a ``.docx``
    without the ``office`` extra) is recorded under
    ``state["permanent_failures"]`` and reported as a ``failed`` row every
    run — but it does NOT set the global ``incomplete`` flag, so later runs
    do not print the resume nag for it.
    """
    state.setdefault("permanent_failures", {})[change.path] = {
        "reason": exc.message,
        "sha256": change.sha256,
    }
    _save_state(target, state)
    hint = f" ({exc.hint})" if exc.hint else ""
    return FileResult(
        path=change.path,
        change="failed",
        detail=f"permanent failure: {exc.message}{hint}",
    )


def _unrecord_if_mine(
    wiring: _Wiring,
    target: Bundle,
    digest: str | None,
    path: str,
    state: dict[str, Any],
) -> None:
    """Drop a stale dedup-manifest record for *digest* when it names *path*.

    The manifest is keyed by content digest; when sync deletes the concepts
    a digest was recorded for, the record must go too — otherwise a later
    plain ``ingest`` would report "already ingested" for content the bundle
    no longer contains. Records naming a *different* path (identical file
    ingested elsewhere) are left alone, and the record is kept whenever any
    *other* state entry still references the digest (shared identical
    content): unrecording it would silently break dedup for live concepts.
    """
    if not digest:
        return
    for other, record in (state.get("sources") or {}).items():
        if other != path and record.get("sha256") == digest:
            return
    try:
        manifest = wiring.load_manifest(target)
    except Exception:  # noqa: BLE001 — manifest is advisory; never fatal
        return
    record = manifest.get(digest)
    if isinstance(record, dict) and record.get("path") == path:
        try:
            wiring.unrecord_digest(target, digest)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Ingest (reuses the ingest command's per-file helpers)
# ---------------------------------------------------------------------------


def _ingest_source(
    path: Path,
    target: Bundle,
    wiring: _Wiring,
    config: SyncConfig,
    *,
    explicit: bool,
) -> tuple[str, int]:
    """Ingest one file; returns the ingest command's (status, count).

    *explicit* marks a source the user named directly (vs. one discovered by
    scanning a directory); explicit sources escalate missing-extra parse
    failures instead of warn-and-skipping (M19, mirroring ``ingest``).
    """
    if config.no_llm:
        return _ingest_no_llm_one(
            path,
            target,
            parse_file=wiring.parse_file,
            ingest_no_llm=wiring.ingest_no_llm,
            sha256_of=wiring.sha256_of,
            already_ingested=wiring.already_ingested,
            record_ingested=wiring.record_ingested,
            sectioning=wiring.sectioning,
            explicit=explicit,
        )
    try:
        return _ingest_llm_one(
            path,
            target,
            parse_file=wiring.parse_file,
            section=wiring.section,
            SectionInput=wiring.SectionInput,
            run=wiring.run,
            model=config.model,
            provider=config.provider,
            api_base=config.api_base,
            api_key=config.api_key,
            explicit=explicit,
        )
    except wiring.LLMUnavailableError as exc:
        raise CliError(
            "llm-unavailable",
            f"LLM unavailable: {exc}",
            "Start Ollama ('ollama serve'), set OKFSMITH_PROVIDER / "
            "OKFSMITH_API_KEY, or retry with --no-llm.",
        ) from None


def _ingest_with_permanent_guard(
    target: Bundle,
    state: dict[str, Any],
    change: _state.FileChange,
    wiring: _Wiring,
    config: SyncConfig,
    *,
    explicit: bool,
) -> tuple[str, int] | FileResult:
    """Ingest one file, converting permanent failures to a ``FileResult``.

    A missing-extra :class:`CliError` (a source that can never succeed
    without user action, e.g. ``.docx`` without the ``office`` extra) is
    recorded via :func:`_record_permanent_failure` and returned as a
    ``failed`` row instead of aborting the pass; every other ``CliError``
    propagates.
    """
    try:
        return _ingest_source(
            Path(change.path), target, wiring, config, explicit=explicit
        )
    except CliError as exc:
        if exc.code == "missing-extra":
            return _record_permanent_failure(target, state, change, exc)
        raise


def _preflight(
    path: Path, wiring: _Wiring, config: SyncConfig, *, explicit: bool
) -> str | None:
    """Check the ingest would-skip gates *before* deleting old concepts.

    Returns ``None`` when ingest should proceed, otherwise the skip/failure
    reason. Updated files whose new content would be skipped keep their old
    concepts (and their old state entry) instead of being wiped. Explicit
    sources escalate missing-extra failures (M19), mirroring ingest.
    """
    from okfsmith.cli.commands import _raise_if_missing_extra

    try:
        parsed = wiring.parse_file(path)
    except Exception as exc:  # noqa: BLE001 — parse_file must never abort sync
        return f"failed: {exc}"
    error = (parsed.meta or {}).get("error")
    if error:
        if explicit:
            _raise_if_missing_extra(path, str(error))
        return f"skipped ({error})"
    try:
        if config.no_llm:
            sectioned = wiring.sectioning.section(parsed)
            if sectioned.too_small:
                return (
                    f"skipped (below {wiring.sectioning.TOO_SMALL_CHARS}-char "
                    "minimum; stub prevention)"
                )
        else:
            if not wiring.section(parsed).sections:
                return "skipped (no sections extracted)"
    except Exception:  # noqa: BLE001 — sectioning must never abort sync
        return "skipped (sectioning failed)"
    return None


def _outcome_of(status: str) -> str:
    if status == "ok":
        return "added"
    if status.startswith("skipped"):
        return "skipped"
    return "failed"


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def _apply_added(
    target: Bundle,
    change: _state.FileChange,
    state: dict[str, Any],
    wiring: _Wiring,
    config: SyncConfig,
    explicit_paths: set[str],
) -> FileResult:
    # Interrupted-sync resume: the concepts may already exist (ingest ran,
    # state save did not). Adopt them instead of creating duplicates.
    existing = [
        cid
        for cid in _state.concepts_from_source(target, change.path)
        if cid not in _referenced_by_others(state, change.path)
    ]
    if existing:
        assert change.sha256 is not None
        _record_source(target, state, change.path, change.sha256, existing)
        return FileResult(
            path=change.path,
            change="added",
            concepts=len(existing),
            detail=f"adopted {len(existing)} existing concept(s)",
        )
    ingested = _ingest_with_permanent_guard(
        target, state, change, wiring, config,
        explicit=change.path in explicit_paths,
    )
    if isinstance(ingested, FileResult):
        return ingested  # permanent failure: already recorded, keep going
    status, _count = ingested
    # A dedup-skipped file shares its content's concepts with the source the
    # manifest names: share ownership instead of recording zero concepts.
    new_ids = _state.concepts_from_source(target, change.path)
    if status == "skipped (already ingested)" and not new_ids:
        new_ids = _donor_concepts(target, wiring, state, change)
    outcome = _outcome_of(status)
    # Skipped/failed files are NOT recorded in the state: the next pass
    # retries them honestly instead of reporting a phantom "unchanged".
    # (The dedup-shared case above is the exception — it is stable.)
    if outcome == "added" or (outcome == "skipped" and new_ids):
        assert change.sha256 is not None
        _record_source(target, state, change.path, change.sha256, new_ids)
    detail = (
        f"{len(new_ids)} concept(s)"
        if outcome == "added"
        else (status if outcome == "skipped" else f"failed: {status}")
    )
    return FileResult(
        path=change.path, change=outcome, concepts=len(new_ids), detail=detail
    )


def _donor_concepts(
    target: Bundle, wiring: _Wiring, state: dict[str, Any], change: _state.FileChange
) -> list[str]:
    """Concept ids of another source with the same content digest, if any."""
    try:
        manifest = wiring.load_manifest(target)
    except Exception:  # noqa: BLE001 — advisory only
        return []
    record = manifest.get(change.sha256 or "")
    donor_path = record.get("path") if isinstance(record, dict) else None
    if donor_path and donor_path != change.path:
        return list(
            (state.get("sources") or {}).get(donor_path, {}).get("concepts") or []
        )
    return []


def _apply_updated(
    target: Bundle,
    change: _state.FileChange,
    state: dict[str, Any],
    wiring: _Wiring,
    config: SyncConfig,
    explicit_paths: set[str],
) -> FileResult:
    path = Path(change.path)
    try:
        reason = _preflight(
            path, wiring, config, explicit=change.path in explicit_paths
        )
    except CliError as exc:
        if exc.code == "missing-extra":
            return _record_permanent_failure(target, state, change, exc)
        raise
    if reason is not None:
        outcome = "failed" if reason.startswith("failed") else "skipped"
        return FileResult(
            path=change.path,
            change=outcome,
            concepts=len(change.concepts),
            detail=reason,
        )
    # Delete the old concepts first (ADD-before-DELETE is about the *plan*
    # order; within one file the old version must go before the re-ingest so
    # the id allocator does not mint -2/-3 duplicates).
    old_ids = _owned_concepts(target, state, change.path)
    removed = _state.remove_concepts(target, old_ids)
    _unrecord_if_mine(wiring, target, change.old_sha256, change.path, state)
    # Content that reverted to a digest recorded for this same path would be
    # dedup-skipped even though its concepts are gone: drop the stale record.
    _unrecord_if_mine(wiring, target, change.sha256, change.path, state)
    ingested = _ingest_with_permanent_guard(
        target, state, change, wiring, config,
        explicit=change.path in explicit_paths,
    )
    if isinstance(ingested, FileResult):
        return ingested  # permanent failure: already recorded, keep going
    status, _count = ingested
    new_ids = _state.concepts_from_source(target, change.path)
    if status == "skipped (already ingested)" and not new_ids:
        new_ids = _donor_concepts(target, wiring, state, change)
    else:
        # The updater's entry records only the concepts its own new content
        # produced: pre-existing concepts shared with other entries (same
        # bytes ingested under another source) keep their original owners.
        # Otherwise a later deletion of the sharer would leave these stale
        # concepts referenced forever.
        shared = _referenced_by_others(state, change.path)
        new_ids = [cid for cid in new_ids if cid not in shared]
    outcome = "updated" if status == "ok" else _outcome_of(status)
    # Like _apply_added: only successful (or stably dedup-shared) outcomes
    # are recorded; skipped/failed files are retried on the next pass.
    if outcome == "updated" or (outcome == "skipped" and new_ids):
        assert change.sha256 is not None
        _record_source(target, state, change.path, change.sha256, new_ids)
    if outcome == "updated":
        detail = f"{len(new_ids)} concept(s) (replaced {len(removed)})"
    elif outcome == "skipped":
        detail = status
    else:
        detail = f"failed: {status}"
    return FileResult(
        path=change.path, change=outcome, concepts=len(new_ids), detail=detail
    )


def _apply_renamed(
    target: Bundle,
    change: _state.FileChange,
    state: dict[str, Any],
) -> FileResult:
    old_path = change.old_path or ""
    ids = _owned_concepts(target, state, old_path)
    moved = 0
    for concept_id in ids:
        concept = target.get(concept_id)
        if concept is None:
            continue
        frontmatter = dict(concept.frontmatter)
        frontmatter["resource"] = change.path
        try:
            # Same id → in-place update; history (log.md, generated stamps)
            # is preserved instead of delete+recreate.
            target.write_concept(concept_id, frontmatter, concept.body)
            moved += 1
        except (OSError, ValueError):
            continue
    record = (state.get("sources") or {}).pop(old_path, {})
    record["sha256"] = change.sha256
    record["concepts"] = sorted(set(ids))
    (state.get("permanent_failures") or {}).pop(old_path, None)
    try:
        stat = Path(change.path).stat()
        record["size"] = stat.st_size
        record["mtime_ns"] = stat.st_mtime_ns
    except OSError:
        pass
    state.setdefault("sources", {})[change.path] = record
    _save_state(target, state)
    return FileResult(
        path=change.path,
        change="renamed",
        concepts=len(ids),
        detail=f"renamed from {_display_path(old_path)} ({moved} concept(s) kept)",
        old_path=old_path,
    )


def _apply_removed(
    target: Bundle,
    change: _state.FileChange,
    state: dict[str, Any],
    wiring: _Wiring,
) -> FileResult:
    sources = state.get("sources") or {}
    my_concepts = set(
        (sources.get(change.path) or {}).get("concepts") or change.concepts
    )
    # Identical content still tracked under another source: transfer
    # ownership, keep the concepts. Sharing is decided by concept-id
    # overlap (the owner list), not by digest equality.
    sharers = [
        other
        for other, record in sources.items()
        if other != change.path
        and my_concepts & set(record.get("concepts") or [])
    ]
    if sharers:
        kept = list(change.concepts)
        sources.pop(change.path, None)
        (state.get("permanent_failures") or {}).pop(change.path, None)
        _save_state(target, state)
        return FileResult(
            path=change.path,
            change="removed",
            concepts=0,
            detail=(
                f"source removed; {len(kept)} concept(s) kept "
                f"(also tracked by {_display_path(sharers[0])})"
            ),
        )
    removed = _state.remove_concepts(
        target, _owned_concepts(target, state, change.path)
    )
    _unrecord_if_mine(wiring, target, change.old_sha256, change.path, state)
    sources.pop(change.path, None)
    (state.get("permanent_failures") or {}).pop(change.path, None)
    _save_state(target, state)
    return FileResult(
        path=change.path,
        change="removed",
        concepts=len(removed),
        detail=f"removed {len(removed)} concept(s)",
    )


def _apply_plan(
    target: Bundle,
    plan: list[_state.FileChange],
    state: dict[str, Any],
    wiring: _Wiring,
    config: SyncConfig,
    explicit_paths: set[str],
) -> list[FileResult]:
    results: list[FileResult] = []
    for change in plan:
        if change.change == "unchanged":
            results.append(
                FileResult(
                    path=change.path,
                    change="unchanged",
                    concepts=len(change.concepts),
                    detail="no changes",
                )
            )
            continue
        try:
            if change.change == "added":
                result = _apply_added(
                    target, change, state, wiring, config, explicit_paths
                )
            elif change.change == "updated":
                result = _apply_updated(
                    target, change, state, wiring, config, explicit_paths
                )
            elif change.change == "renamed":
                result = _apply_renamed(target, change, state)
            elif change.change == "removed":
                result = _apply_removed(target, change, state, wiring)
            else:  # pragma: no cover — plan_sync only emits known changes
                raise AssertionError(f"unknown change {change.change!r}")
        except CliError:
            raise
        except Exception as exc:  # noqa: BLE001 — per-file failure, keep going
            result = FileResult(
                path=change.path, change="failed", detail=f"{exc}"
            )
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# One sync pass
# ---------------------------------------------------------------------------


def run_once(
    bundle_path: Path,
    sources: list[Path],
    config: SyncConfig,
    _wiring: _Wiring | None = None,
) -> SyncResult:
    """Run a single sync pass: detect changes, apply them, update the state.

    Non-dry-run passes hold the per-bundle sync lock
    (``<bundle>/.okfsmith/sync.lock``); a second concurrent sync fails fast
    with ``error [sync-locked]`` instead of clobbering the state.
    """
    wiring = _wiring or _wiring_factory(config.no_llm)
    try:
        target = Bundle.load(bundle_path)
    except OSError as exc:
        raise CliError(
            "io-error",
            f"cannot open bundle directory '{bundle_path}': {exc}",
            "Check the path is writable and not on a read-only filesystem.",
        ) from None

    scan = _scan_files(sources, config.recursive, bundle_root=Path(target.root))
    roots = sorted({str(source.resolve()) for source in sources})
    # M19 parity with ingest: only sources the user named directly as files
    # escalate missing-extra parse failures; directory-discovered files
    # warn-and-skip.
    explicit_paths = {
        str(source.resolve()) for source in sources if source.is_file()
    }
    state = _state.load_sync_state(target)
    resumed = bool(state.get("incomplete"))
    scoped = _state.scoped_sources(state, roots)
    current, hash_failed = _hash_files(scan.files, wiring)
    plan = _state.plan_sync(current, scoped)

    results: list[FileResult] = list(scan.skipped)
    results.extend(hash_failed)
    if not config.dry_run:
        # Drop permanent-failure marks for files that no longer exist: the
        # user fixed the problem by deleting the source.
        failures = state.get("permanent_failures") or {}
        for failed_path in [p for p in failures if p not in current]:
            del failures[failed_path]
    if config.dry_run:
        for change in plan:
            detail = {
                "added": "would ingest",
                "updated": "would re-ingest (old concepts replaced)",
                "renamed": f"would rename from {_display_path(change.old_path or '')}",
                "removed": "would remove concepts",
                "unchanged": "no changes",
            }[change.change]
            results.append(
                FileResult(
                    path=change.path,
                    change=change.change,
                    concepts=len(change.concepts),
                    detail=detail,
                    old_path=change.old_path,
                )
            )
        return SyncResult(results=results, resumed=resumed, dry_run=True)

    if scan.bundle_skipped and not config.quiet:
        typer.echo(
            f"note: skipped {scan.bundle_skipped} file(s) inside the bundle "
            f"directory '{bundle_path}' — a bundle is never scanned as a "
            "source.",
            err=True,
        )
    if resumed:
        typer.echo(
            "note: the previous sync did not complete; resuming.",
            err=True,
        )

    # Dry runs never take the lock (they write nothing); every mutating
    # pass serializes on it.
    release = None
    try:
        release = _state.acquire_sync_lock(target)
    except _state.SyncLockedError as exc:
        raise CliError(
            "sync-locked",
            str(exc),
            "If no sync is actually running, delete "
            f"'{_state.sync_lock_path(target)}' and retry.",
        ) from None
    except _state.SyncStateSymlinkError as exc:
        raise CliError(
            "sync-refused",
            str(exc),
            "Remove the symlink so '<bundle>/.okfsmith/' is a real "
            "directory inside the bundle, then retry.",
        ) from None
    try:
        return _run_pass(
            target, bundle_path, plan, state, wiring, config, explicit_paths,
            results, resumed,
        )
    finally:
        if release is not None:
            release()


def _run_pass(
    target: Bundle,
    bundle_path: Path,
    plan: list[_state.FileChange],
    state: dict[str, Any],
    wiring: _Wiring,
    config: SyncConfig,
    explicit_paths: set[str],
    results: list[FileResult],
    resumed: bool,
) -> SyncResult:
    """Apply *plan* under the sync lock; see :func:`run_once`."""
    state["incomplete"] = True
    try:
        _save_state(target, state)
    except OSError as exc:
        raise CliError(
            "io-error",
            f"cannot write sync state in '{bundle_path}': {exc}",
            "Check the bundle directory is writable.",
        ) from None

    # A CliError (e.g. llm-unavailable, io-error) aborts the pass with the
    # incomplete flag still set, so the next run resumes cleanly.
    results.extend(_apply_plan(target, plan, state, wiring, config, explicit_paths))

    summary = SyncResult(results=results).summary()
    changed = sum(summary[name] for name in ("added", "updated", "renamed", "removed"))
    if changed:
        try:
            indexlog.ensure_index(target)
            indexlog.append_log(
                target,
                kind="Update",
                message=(
                    f"Sync: {summary['added']} added, {summary['updated']} updated, "
                    f"{summary['renamed']} renamed, {summary['removed']} removed."
                ),
            )
        except OSError as exc:
            raise CliError(
                "io-error",
                f"could not update bundle '{bundle_path}': {exc}",
                "Check the bundle directory is writable.",
            ) from None
    state["incomplete"] = False
    try:
        _save_state(target, state)
    except OSError as exc:
        raise CliError(
            "io-error",
            f"cannot write sync state in '{bundle_path}': {exc}",
            "Check the bundle directory is writable.",
        ) from None
    return SyncResult(results=results, resumed=resumed, dry_run=False)


def _wiring_factory(no_llm: bool) -> _Wiring:
    return _wiring(no_llm)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def print_result(
    result: SyncResult,
    bundle_path: Path,
    sources: list[Path],
    *,
    output_format: str = "text",
    quiet: bool = False,
    jsonl: bool = False,
) -> None:
    """Render a sync result as a rich table or JSON.

    With ``jsonl=True`` (used by ``--watch``) the JSON form is a single
    compact object on one line — the watch stream is JSONL: one object per
    line, one per cycle.
    """
    if output_format == "json":
        payload = {
            "bundle": str(bundle_path),
            "sources": [str(source) for source in sources],
            "dry_run": result.dry_run,
            "resumed": result.resumed,
            "summary": result.summary(),
            "files": [
                {
                    "path": item.path,
                    "change": item.change,
                    "old_path": item.old_path,
                    "concepts": item.concepts,
                    "detail": item.detail,
                }
                for item in result.results
            ],
        }
        if jsonl:
            typer.echo(json.dumps(_jsonable(payload), separators=(",", ":")))
        else:
            _dump_json(payload)
        return
    if not quiet:
        table = Table(title=f"Sync summary — {bundle_path}")
        table.add_column("File")
        table.add_column("Change")
        table.add_column("Concepts", justify="right")
        table.add_column("Detail")
        for item in result.results:
            style = _OUTCOME_STYLE.get(item.change, "")
            table.add_row(
                escape(_display_path(item.path)),
                f"[{style}]{escape(item.change)}[/{style}]",
                str(item.concepts),
                escape(item.detail),
            )
        console.print(table)
    summary = result.summary()
    parts = [f"{summary[name]} {name}" for name in OUTCOME_ORDER]
    suffix = " (dry run — nothing written)" if result.dry_run else ""
    typer.echo(f"sync: {', '.join(parts)} → {bundle_path}{suffix}")


def _summary_line(summary: dict[str, int]) -> str:
    return (
        f"{_plural(summary['added'], 'file')} added, "
        f"{_plural(summary['updated'], 'file')} updated, "
        f"{_plural(summary['renamed'], 'file')} renamed, "
        f"{_plural(summary['removed'], 'file')} removed"
    )


# ---------------------------------------------------------------------------
# Watch mode (polling)
# ---------------------------------------------------------------------------


def _build_snapshot(
    sources: list[Path],
    recursive: bool,
    wiring: _Wiring,
    state: dict[str, Any],
    bundle_root: Path | None = None,
) -> dict[str, tuple[int, int, str | None]]:
    """``{path: (mtime_ns, size, sha256)}``; SHA-256 seeded from the state.

    Files whose mtime+size match the recorded state reuse the recorded
    digest (fast path); anything else is hashed (SHA-256 confirm).
    """
    snapshot: dict[str, tuple[int, int, str | None]] = {}
    for path in _scan_files(
        sources, recursive, bundle_root=bundle_root
    ).files:
        key = str(path)
        try:
            stat = path.stat()
        except OSError:
            continue
        record = (state.get("sources") or {}).get(key) or {}
        if (
            record.get("mtime_ns") == stat.st_mtime_ns
            and record.get("size") == stat.st_size
            and record.get("sha256")
        ):
            sha: str | None = record["sha256"]
        else:
            try:
                sha = wiring.sha256_of(path)
            except OSError:
                continue
        snapshot[key] = (stat.st_mtime_ns, stat.st_size, sha)
    return snapshot


def _poll_changed(
    sources: list[Path],
    recursive: bool,
    wiring: _Wiring,
    snapshot: dict[str, tuple[int, int, str | None]],
    bundle_root: Path | None = None,
) -> bool:
    """True when a re-sync is warranted; updates *snapshot* in place.

    mtime+size is the fast path; a changed fast-path signature is confirmed
    with SHA-256 before reporting a change (a bare ``touch`` does not sync).
    """
    try:
        files = _scan_files(sources, recursive, bundle_root=bundle_root).files
    except CliError:
        # A source vanished mid-watch; the sync pass reports it cleanly.
        return True
    current_paths = {str(path) for path in files}
    if set(snapshot) != current_paths:
        return True  # file added or deleted
    changed = False
    for path in files:
        key = str(path)
        try:
            stat = path.stat()
        except OSError:
            continue
        mtime_ns, size, sha = snapshot[key]
        if (stat.st_mtime_ns, stat.st_size) != (mtime_ns, size):
            try:
                new_sha = wiring.sha256_of(path)
            except OSError:
                continue
            snapshot[key] = (stat.st_mtime_ns, stat.st_size, new_sha)
            if new_sha != sha:
                changed = True
    return changed


def run_watch(
    bundle_path: Path,
    sources: list[Path],
    config: SyncConfig,
    *,
    interval: float,
    output_format: str = "text",
    quiet: bool = False,
    stop_event: threading.Event | None = None,
    max_cycles: int | None = None,
) -> None:
    """Polling watch loop: initial sync, then re-sync on confirmed changes.

    Exits cleanly on Ctrl-C (exit 0 via the caller) or when *stop_event* is
    set. *max_cycles* bounds the loop for tests; ``None`` watches forever.
    A failing cycle is reported and the watch continues.
    """
    wiring = _wiring(config.no_llm)
    target = Bundle(bundle_path)  # no I/O; only used for the state path
    bundle_root = Path(target.root)
    state = _state.load_sync_state(target)
    snapshot = _build_snapshot(
        sources, config.recursive, wiring, state, bundle_root=bundle_root
    )

    def emit(result: SyncResult) -> None:
        # Watch-mode JSON is JSONL: one compact object per line, per cycle.
        print_result(
            result,
            bundle_path,
            sources,
            output_format=output_format,
            quiet=quiet,
            jsonl=True,
        )

    def cycle() -> None:
        try:
            result = run_once(bundle_path, sources, config, _wiring=wiring)
        except CliError as exc:
            # A failing cycle must not kill the watch; report and continue.
            typer.echo(f"error [{exc.code}]: {exc.message}", err=True)
            if exc.hint:
                typer.echo(f"hint: {exc.hint}", err=True)
            return
        emit(result)
        state_now = _state.load_sync_state(Bundle(bundle_path))
        snapshot.clear()
        snapshot.update(
            _build_snapshot(
                sources, config.recursive, wiring, state_now,
                bundle_root=bundle_root,
            )
        )

    typer.echo(
        f"watching {len(sources)} source(s) every {interval:g}s "
        "— Ctrl-C to stop",
        err=True,
    )
    stop = stop_event or threading.Event()
    cycles = 0
    try:
        cycle()  # initial pass: bring the state up to date immediately
        while True:
            if stop.wait(interval):
                break
            if _poll_changed(
                sources, config.recursive, wiring, snapshot,
                bundle_root=bundle_root,
            ):
                cycle()
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                break
    except KeyboardInterrupt:
        pass
    typer.echo("stopped watching.", err=True)


__all__ = [
    "FileResult",
    "SyncConfig",
    "SyncResult",
    "_wiring",
    "print_result",
    "run_once",
    "run_watch",
]
