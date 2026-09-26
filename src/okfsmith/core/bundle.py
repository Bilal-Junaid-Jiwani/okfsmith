"""Bundle: the on-disk OKF knowledge bundle (concepts + index.md + log.md).

A bundle is a directory tree of ``*.md`` concept documents. Reserved files
(``index.md``, ``log.md`` — see :mod:`okfsmith.core.spec`) are never concepts.
A concept's id is its path relative to the bundle root, minus the ``.md``
suffix, with forward slashes (e.g. ``finance/revenue``).

No network calls; stdlib only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from okfsmith.core import frontmatter as _fm
from okfsmith.core.spec import RESERVED_FILES

_SUFFIX = ".md"


def slugify(value: str) -> str:
    """Slugify *value*: lowercase, runs of non-alphanumerics become ``-``.

    >>> slugify("Hello, World!")
    'hello-world'
    """
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "untitled"


def concept_path_for(root: Path, concept_id: str) -> Path:
    """Map a concept id to its on-disk path, slugifying each ``/`` segment.

    ``"Notes/Hello World"`` under ``root`` → ``root/notes/hello-world.md``.
    """
    parts = [slugify(part) for part in concept_id.replace("\\", "/").split("/")]
    return root.joinpath(*parts).with_suffix(_SUFFIX)


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
    def load(cls, root: str | Path) -> "Bundle":
        """Walk *root* and parse every ``*.md`` file into a :class:`Concept`.

        Files named ``index.md`` / ``log.md`` are skipped as concepts; the
        root ``index.md`` / ``log.md`` are read into ``index_text`` /
        ``log_text``. Missing reserved files are fine (``None``).
        """
        bundle = cls(root)
        bundle.root.mkdir(parents=True, exist_ok=True)
        for md in sorted(bundle.root.rglob(f"*{_SUFFIX}")):
            if md.name in RESERVED_FILES:
                continue
            # Security (audit-3 finding 3): never follow symlinks when
            # loading a bundle. A shared bundle containing
            # ``evil.md -> /etc/passwd`` must not have host files parsed
            # into concepts (and later into viz.html / MCP output).
            if md.is_symlink():
                continue
            rel = md.relative_to(bundle.root)
            concept_id = rel.with_suffix("").as_posix()
            data, body = _fm.parse_frontmatter(md.read_text(encoding="utf-8"))
            bundle._concepts[concept_id] = Concept(
                id=concept_id, path=md, frontmatter=data, body=body
            )
        for filename, attr in (("index.md", "index_text"), ("log.md", "log_text")):
            candidate = bundle.root / filename
            # Same symlink rule as concepts: never read through a symlink
            # (audit-3 finding 3).
            if candidate.is_file() and not candidate.is_symlink():
                setattr(bundle, attr, candidate.read_text(encoding="utf-8"))
        return bundle

    def write_concept(self, concept_id: str, frontmatter: dict, body: str) -> Concept:
        """Write a concept document to disk and register it in this bundle.

        The id is slugified segment-by-segment to derive the file path
        (parent directories are created). The returned :class:`Concept`'s
        ``id`` is the slugified id, so it round-trips through :meth:`load`.
        Unknown frontmatter keys are written back untouched.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        path = concept_path_for(self.root, concept_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_fm.serialize_frontmatter(frontmatter, body), encoding="utf-8")
        stored_id = path.relative_to(self.root).with_suffix("").as_posix()
        concept = Concept(
            id=stored_id, path=path, frontmatter=dict(frontmatter), body=body
        )
        self._concepts[stored_id] = concept
        return concept

    def iter_concepts(self) -> Iterator[Concept]:
        """Yield all concepts, sorted by id for deterministic output."""
        for concept_id in sorted(self._concepts):
            yield self._concepts[concept_id]

    def get(self, concept_id: str) -> Concept | None:
        """Return the concept with *concept_id*, or ``None`` if absent."""
        return self._concepts.get(concept_id)
