"""Generation of OKF reserved files: ``index.md`` and ``log.md``.

Conventions (match the repo's ``.contract/fixtures``):

- Index entries: ``* [Title](path) - description`` — links are bundle-relative,
  forward slashes, **without** the ``.md`` suffix; the ``- description`` part
  is omitted when the concept has no description.
- Only the *root* ``index.md`` carries frontmatter, and it is exactly
  ``okf_version: "0.2"``. Subdirectory indexes are plain markdown.
- Log entries: ``* **Kind**: message`` under ``## YYYY-MM-DD`` headings,
  newest first (both headings and entries within a day).

Write-path hardening (QA audit):

- C1: every write is confined to the bundle root. The target directory is
  resolved with ``os.path.realpath`` and refused when it escapes the root;
  an ``index.md``/``log.md`` that is itself a symlink is refused as well —
  matching :meth:`Bundle.load`, which never reads through such symlinks.
- M5: log messages are collapsed to a single line (log-forgery hardening).
- M6: ``]`` in concept titles is backslash-escaped so a crafted title cannot
  break out of the ``[...]`` link-text span in the generated index.
- H2/M30: ``index.md``/``log.md`` are written atomically (temp file in the
  same directory + ``os.replace``); ``append_log`` additionally holds a
  best-effort ``fcntl`` exclusive lock around its read-modify-write so
  concurrent appends cannot lose entries.

No network calls; stdlib only.
"""

from __future__ import annotations

import contextlib
import os
import posixpath
import re
import tempfile
from pathlib import Path

from okfsmith.core import frontmatter as _fm
from okfsmith.core.bundle import Bundle
from okfsmith.core.spec import OKF_VERSION, today_iso

try:  # fcntl is absent on Windows; the append lock below is best-effort (M30).
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

#: Allowed ``log.md`` entry kinds.
LOG_KINDS = frozenset({"Creation", "Update", "Deprecation"})

_HEADING_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)

_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _norm_subdir(subdir: str) -> str:
    cleaned = subdir.strip().strip("/")
    # Security (audit-3 finding 6): reject ``..`` so a library caller (or a
    # future CLI flag) cannot make ensure_index/append_log write outside the
    # bundle root.
    normalized = posixpath.normpath(cleaned) if cleaned else ""
    if normalized == ".." or normalized.startswith("../"):
        raise ValueError(f"invalid subdir {subdir!r}: must stay inside the bundle")
    return normalized if normalized != "." else ""


def _one_line(value: object) -> str:
    """Collapse all whitespace (including newlines) to single spaces.

    Log entries are one line each; without this a crafted message could forge
    backdated ``## YYYY-MM-DD`` headings or fake entries (audit M5).
    """
    return " ".join(str(value).split())


def _escape_link_text(text: str) -> str:
    """Escape *text* for interpolation as a markdown link label (audit M6).

    A backslash-escaped ``]`` cannot terminate the ``[...]`` link-text span,
    so a crafted title like ``x](http://evil.example/phish)`` renders as
    literal text instead of hijacking the link target.
    """
    return text.replace("]", "\\]")


def _is_within_root(resolved: str, root_real: str) -> bool:
    return resolved == root_real or resolved.startswith(root_real.rstrip(os.sep) + os.sep)


def _confined_dir(bundle: Bundle, subdir: str) -> Path:
    """Return the on-disk directory for *subdir*, confined to the bundle root.

    Raises ``ValueError`` when any path component (including symlinks) resolves
    outside the bundle root (audit C1).
    """
    target = bundle.root if not subdir else bundle.root / subdir
    root_real = os.path.realpath(bundle.root)
    resolved = os.path.realpath(target)
    if not _is_within_root(resolved, root_real):
        raise ValueError(
            f"refusing to write outside the bundle root: {str(target)!r} "
            f"resolves to {resolved!r}"
        )
    return target


def _ensure_confined_dir(bundle: Bundle, subdir: str) -> Path:
    """Create the confined target directory, re-checking after creation.

    The post-mkdir re-check is a best-effort TOCTOU backstop against a symlink
    swapped in between the check and the write.
    """
    _confined_dir(bundle, subdir).mkdir(parents=True, exist_ok=True)
    return _confined_dir(bundle, subdir)


def _refuse_symlink(path: Path) -> None:
    """Refuse to write through a symlinked reserved file (audit C1).

    Mirrors :meth:`Bundle.load`, which never reads through a symlinked
    ``index.md``/``log.md``.
    """
    if path.is_symlink():
        raise ValueError(f"refusing to write through symlink: {path}")


def _atomic_write_text(path: Path, text: str) -> None:
    """Write *text* to *path* atomically: temp file in the same dir + rename.

    Readers never observe a partially written file (audit H2); on failure the
    original file is untouched and the temp file is removed.
    """
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


@contextlib.contextmanager
def _exclusive_dir_lock(dir_path: Path):
    """Hold a best-effort exclusive lock serializing writers to *dir_path*.

    The directory inode is stable across the atomic renames used for the
    reserved files, so — unlike locking ``log.md`` itself, whose inode is
    replaced by every write — this genuinely serializes concurrent
    ``append_log`` writers (audit M30). On platforms without ``fcntl``, or if
    the lock cannot be taken, the write proceeds without it (best-effort).
    """
    fd = None
    try:
        fd = os.open(dir_path, os.O_RDONLY)
    except OSError:
        fd = None  # best-effort: proceed without the lock
    try:
        if fd is not None and fcntl is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
            except OSError:
                pass  # best-effort: proceed without the lock
        yield
    finally:
        if fd is not None:
            os.close(fd)


def _read_fd_text(fd: int) -> str:
    """Read all text from *fd* (opened ``O_NOFOLLOW``; never via a symlink)."""
    os.lseek(fd, 0, os.SEEK_SET)
    chunks = []
    while True:
        data = os.read(fd, 65536)
        if not data:
            break
        chunks.append(data)
    return b"".join(chunks).decode("utf-8")


def _read_reserved_text(path: Path) -> str:
    """Read *path* without following a symlink (fail-closed on a race).

    The caller must already have refused pre-existing symlinks (C1); the
    ``O_NOFOLLOW`` open additionally refuses a symlink swapped in between
    the check and the read.
    """
    if not path.is_file():
        return ""
    fd = os.open(path, os.O_RDONLY | _O_NOFOLLOW)
    try:
        return _read_fd_text(fd)
    finally:
        os.close(fd)


def _render_log_text(existing: str, today: str, entry: str) -> str:
    """Insert *entry* under today's ``## YYYY-MM-DD`` heading, newest first."""
    if not existing.strip():
        text = f"# Log\n\n## {today}\n\n{entry}\n"
    else:
        lines = existing.splitlines()
        first_heading = next(
            (i for i, line in enumerate(lines) if _HEADING_RE.match(line)), None
        )
        if first_heading is not None and lines[first_heading].strip() == f"## {today}":
            insert_at = first_heading + 1
            while insert_at < len(lines) and not lines[insert_at].strip():
                insert_at += 1
            lines.insert(insert_at, entry)
            text = "\n".join(lines)
        else:
            text = f"## {today}\n\n{entry}\n\n" + existing.lstrip("\n")
    if not text.endswith("\n"):
        text += "\n"
    return text


def _title_for(concept_id: str, frontmatter: dict) -> str:
    title = frontmatter.get("title")
    if title:
        return str(title)
    return concept_id.rsplit("/", 1)[-1].replace("-", " ").replace("_", " ").title()


def ensure_index(bundle: Bundle, subdir: str = "") -> Path:
    """Generate (or refresh) ``index.md`` for *subdir*, listing its concepts.

    *subdir* ``""`` (the default) means the bundle root. The root index lists
    every concept recursively; a subdirectory index lists the concepts under
    that directory, with links relative to it.

    Only the root index gets frontmatter (``okf_version: "0.2"``); subdirectory
    indexes are plain markdown. The file is written to disk atomically,
    ``index_text`` is refreshed for the root index, and the path is returned.

    Raises ``ValueError`` if *subdir* (after symlink resolution) escapes the
    bundle root, or if the target ``index.md`` is a symlink.
    """
    subdir = _norm_subdir(subdir)
    index_dir = _ensure_confined_dir(bundle, subdir)
    prefix = f"{subdir}/" if subdir else ""

    entries: list[tuple[str, str]] = []  # (sort key, line)
    for concept in bundle.iter_concepts():
        if prefix and not concept.id.startswith(prefix):
            continue
        raw_title = _title_for(concept.id, concept.frontmatter)
        title = _escape_link_text(raw_title)
        link = concept.id[len(prefix) :] if prefix else concept.id
        description = str(concept.frontmatter.get("description") or "").strip()
        line = f"* [{title}]({link})"
        if description:
            line += f" - {description}"
        entries.append((raw_title.casefold(), line))
    entries.sort(key=lambda item: item[0])

    heading = "# Index" if not subdir else f"# {subdir.rsplit('/', 1)[-1].title()}"
    body = heading + "\n\n" + "\n".join(line for _, line in entries) + "\n"
    if subdir:
        text = body
    else:
        text = _fm.serialize_frontmatter({"okf_version": OKF_VERSION}, body)

    index_path = index_dir / "index.md"
    _refuse_symlink(index_path)
    _atomic_write_text(index_path, text)
    if not subdir:
        bundle.index_text = text
    return index_path


def append_log(
    bundle: Bundle, subdir: str = "", kind: str = "Update", message: str = ""
) -> Path:
    """Append an entry to ``log.md`` in *subdir*, newest-first.

    *kind* must be one of ``{"Creation", "Update", "Deprecation"}``
    (``ValueError`` otherwise). The message is collapsed to a single line so
    it cannot forge headings or entries. The entry goes under a
    ``## YYYY-MM-DD`` heading for today (UTC); if no such heading exists yet
    it is created at the top of the file. Within a day, newer entries come
    first. The file is written to disk atomically under a best-effort
    exclusive lock, ``log_text`` is refreshed for the root log, and the path
    is returned.

    Raises ``ValueError`` if *subdir* (after symlink resolution) escapes the
    bundle root, or if the target ``log.md`` is a symlink.
    """
    if kind not in LOG_KINDS:
        raise ValueError(f"kind must be one of {sorted(LOG_KINDS)}; got {kind!r}")
    subdir = _norm_subdir(subdir)
    log_dir = _ensure_confined_dir(bundle, subdir)
    log_path = log_dir / "log.md"
    _refuse_symlink(log_path)

    today = today_iso()
    entry = f"* **{kind}**: {_one_line(message)}"

    # The directory lock serializes concurrent writers; the inode it locks
    # is stable across the atomic rename below (audit M30).
    with _exclusive_dir_lock(log_dir):
        # Re-check under the lock: refuse a symlinked log.md (audit C1).
        _refuse_symlink(log_path)
        existing = _read_reserved_text(log_path)
        text = _render_log_text(existing, today, entry)
        # os.replace never follows a symlink at the destination: even a
        # racing symlink swap is replaced, not traversed.
        _atomic_write_text(log_path, text)

    if not subdir:
        bundle.log_text = text
    return log_path
