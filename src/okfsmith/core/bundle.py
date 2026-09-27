"""Bundle: the on-disk OKF knowledge bundle (concepts + index.md + log.md).

A bundle is a directory tree of ``*.md`` concept documents. Reserved files
(``index.md``, ``log.md`` — see :mod:`okfsmith.core.spec`) are never concepts.
A concept's id is its path relative to the bundle root, minus the ``.md``
suffix, with forward slashes (e.g. ``finance/revenue``).

No network calls; stdlib only.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from okfsmith.core import frontmatter as _fm
from okfsmith.core.spec import RESERVED_FILES

_SUFFIX = ".md"
# Per-component filename limit on common filesystems (bytes, incl. suffix).
_MAX_FILENAME_BYTES = 255


class BundleError(Exception):
    """A bundle file could not be read (e.g. it is not valid UTF-8).

    Raised instead of a raw :exc:`UnicodeDecodeError` so callers (notably
    the CLI) can surface a clean ``error [io-error]`` without a traceback.
    """


def slugify(value: str) -> str:
    """Slugify *value*: NFC-normalized, lowercased, runs of non-alphanumerics become ``-``.

    Normalizing to NFC first means visually identical titles (``café`` in
    NFC vs NFD) map to the same slug instead of diverging.

    >>> slugify("Hello, World!")
    'hello-world'
    """
    normalized = unicodedata.normalize("NFC", value)
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return slug or "untitled"


def _fit_filename_stem(stem: str) -> str:
    """Truncate *stem* so ``stem + ".md"`` fits in 255 bytes.

    Pure byte truncation — deterministic, so the same input always yields
    the same filename. A partial multibyte character at the cut is dropped.
    """
    limit = _MAX_FILENAME_BYTES - len(_SUFFIX)
    raw = stem.encode("utf-8")
    if len(raw) <= limit:
        return stem
    return raw[:limit].decode("utf-8", errors="ignore") or "untitled"


def _slug_id(concept_id: str) -> str:
    """Slugify *concept_id* segment-by-segment into a load-stable id.

    Each segment is NFC-normalized, slugified, and truncated so no
    filename exceeds the 255-byte component limit.
    """
    normalized = unicodedata.normalize("NFC", concept_id)
    segments = [slugify(part) for part in normalized.replace("\\", "/").split("/")]
    return "/".join(_fit_filename_stem(segment) for segment in segments)


def _suffixed_id(base_id: str, n: int) -> str:
    """Append ``-n`` to the last segment of *base_id*, keeping it filename-safe."""
    *head, last = base_id.split("/")
    suffix = f"-{n}"
    limit = _MAX_FILENAME_BYTES - len(_SUFFIX) - len(suffix.encode("utf-8"))
    raw = last.encode("utf-8")
    if len(raw) > limit:
        last = raw[:limit].decode("utf-8", errors="ignore") or "untitled"
    return "/".join([*head, f"{last}{suffix}"])


def concept_path_for(root: Path, concept_id: str) -> Path:
    """Map a concept id to its on-disk path, slugifying each ``/`` segment.

    ``"Notes/Hello World"`` under ``root`` → ``root/notes/hello-world.md``.
    Segments are truncated so no filename exceeds 255 bytes (deterministic:
    the same id always maps to the same path).
    """
    return root.joinpath(*_slug_id(concept_id).split("/")).with_suffix(_SUFFIX)


@dataclass
class Concept:
    """A single OKF concept document."""

    id: str
    """Concept id: path relative to the bundle root, minus ``.md``, forward slashes."""

    path: Path
    """Absolute path of the ``.md`` file on disk."""

    frontmatter: dict = field(default_factory=dict)
    """Parsed YAML frontmatter; unknown keys preserved as-is."""

    body: str = ""
    """Markdown body after the frontmatter block."""


class Bundle:
    """An OKF knowledge bundle rooted at a directory on disk."""

    def __init__(self, root: str | Path) -> None:
        """Create a bundle handle for *root* (nothing is read yet)."""
        self.root = Path(root).resolve()
        self._concepts: dict[str, Concept] = {}
        self.index_text: str | None = None
        """Raw text of the root ``index.md``, if present when loaded."""
        self.log_text: str | None = None
        """Raw text of the root ``log.md``, if present when loaded."""

    @classmethod
    def load(cls, root: str | Path) -> Bundle:
        """Walk *root* and parse every ``*.md`` file into a :class:`Concept`.

        Files named ``index.md`` / ``log.md`` (any casing) are skipped as
        concepts; the root ``index.md`` / ``log.md`` are read into
        ``index_text`` / ``log_text``. Missing reserved files are fine
        (``None``). Directories named ``*.md`` and non-regular files
        (FIFOs, sockets, …) are skipped rather than read. A file that is
        not valid UTF-8 raises :class:`BundleError` naming the file.
        """
        bundle = cls(root)
        bundle.root.mkdir(parents=True, exist_ok=True)
        for md in sorted(bundle.root.rglob(f"*{_SUFFIX}")):
            # Security (audit-3 finding 3): never follow symlinks when
            # loading a bundle. A shared bundle containing
            # ``evil.md -> /etc/passwd`` must not have host files parsed
            # into concepts (and later into viz.html / MCP output).
            if md.is_symlink():
                continue
            # Robustness (QA H12/H17): skip directories named "*.md" and
            # non-regular files (FIFOs would block forever on read).
            if not md.is_file():
                continue
            # Reserved names are never concepts; the check is
            # case-insensitive (QA L23) so e.g. "Index.md" cannot slip in
            # as a concept on case-sensitive filesystems.
            if md.name.lower() in RESERVED_FILES:
                continue
            rel = md.relative_to(bundle.root)
            concept_id = rel.with_suffix("").as_posix()
            try:
                data, body = _fm.parse_frontmatter(md.read_text(encoding="utf-8"))
            except UnicodeDecodeError as exc:
                raise BundleError(
                    f"cannot read {rel.as_posix()}: file is not valid UTF-8"
                ) from exc
            bundle._concepts[concept_id] = Concept(
                id=concept_id, path=md, frontmatter=data, body=body
            )
        for filename, attr in (("index.md", "index_text"), ("log.md", "log_text")):
            candidate = bundle.root / filename
            # Same symlink rule as concepts: never read through a symlink
            # (audit-3 finding 3).
            if candidate.is_file() and not candidate.is_symlink():
                try:
                    text = candidate.read_text(encoding="utf-8")
                except UnicodeDecodeError as exc:
                    raise BundleError(
                        f"cannot read {filename}: file is not valid UTF-8"
                    ) from exc
                setattr(bundle, attr, text)
        return bundle

    def write_concept(self, concept_id: str, frontmatter: dict, body: str) -> Concept:
        """Write a concept document to disk and register it in this bundle.

        The id is slugified segment-by-segment to derive the file path
        (parent directories are created); over-long segments are truncated
        so no filename exceeds 255 bytes, deterministically. The returned
        :class:`Concept`'s ``id`` is the slugified id, so it round-trips
        through :meth:`load`. Unknown frontmatter keys are written back
        untouched.

        Raises :exc:`ValueError` if the id maps to a reserved filename
        (``index`` / ``log`` in any casing): reserved files are never
        silently overwritten.

        If the slug-derived path is already taken by a *different* concept
        id, ``-2``, ``-3``, … is appended until the path is free, so an
        existing concept is never overwritten. Re-writing the exact same
        concept id updates that concept in place.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        base_id = _slug_id(concept_id)
        for segment in base_id.split("/"):
            # Segments are slugified (hence lowercase), so this check is
            # case-insensitive by construction: "Index", "LOG", …
            if f"{segment}{_SUFFIX}" in RESERVED_FILES:
                raise ValueError(
                    f"refusing to write concept {concept_id!r}: "
                    f"{segment + _SUFFIX!r} is a reserved bundle filename; "
                    "concepts may not be named 'index' or 'log' (any casing)"
                )
        candidate_id = base_id
        if self._path_taken_by_other(candidate_id, concept_id):
            n = 2
            while self._path_taken_by_other(_suffixed_id(base_id, n), concept_id):
                n += 1
            candidate_id = _suffixed_id(base_id, n)
        path = concept_path_for(self.root, candidate_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_fm.serialize_frontmatter(frontmatter, body), encoding="utf-8")
        stored_id = path.relative_to(self.root).with_suffix("").as_posix()
        concept = Concept(
            id=stored_id, path=path, frontmatter=dict(frontmatter), body=body
        )
        self._concepts[stored_id] = concept
        return concept

    def _path_taken_by_other(self, candidate_id: str, requested_id: str) -> bool:
        """Whether *candidate_id*'s path belongs to a different concept.

        A registered concept carrying the exact requested id string is an
        in-place update, not a collision. A path already present on disk
        but unknown to this handle (e.g. written through another
        :class:`Bundle`) is treated as taken so it is never clobbered.
        """
        occupant = self.get(candidate_id)
        if occupant is not None:
            return occupant.id != requested_id
        return concept_path_for(self.root, candidate_id).exists()

    def iter_concepts(self) -> Iterator[Concept]:
        """Yield all concepts, sorted by id for deterministic output."""
        for concept_id in sorted(self._concepts):
            yield self._concepts[concept_id]

    def get(self, concept_id: str) -> Concept | None:
        """Return the concept with *concept_id*, or ``None`` if absent."""
        return self._concepts.get(concept_id)

    def delete_concept(self, concept_id: str) -> bool:
        """Delete a concept: remove its ``.md`` file and unregister it.

        Returns ``True`` when a concept was removed. The file must resolve
        inside the bundle root and must not be a symlink; anything else
        (unknown id, escaping path, symlink, unlink failure) returns
        ``False`` instead of raising, so batch deletions never abort midway.
        """
        concept = self._concepts.get(concept_id)
        if concept is None:
            return False
        try:
            resolved = concept.path.resolve()
        except OSError:
            return False
        try:
            resolved.relative_to(self.root)
        except ValueError:
            # Escapes the bundle root: refuse to touch it.
            return False
        if resolved.is_symlink() or not resolved.is_file():
            return False
        try:
            resolved.unlink()
        except OSError:
            return False
        self._concepts.pop(concept_id, None)
        return True
