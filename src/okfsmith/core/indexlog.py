"""Generation of OKF reserved files: ``index.md`` and ``log.md``.

Conventions (match the repo's ``.contract/fixtures``):

- Index entries: ``* [Title](path) - description`` — links are bundle-relative,
  forward slashes, **without** the ``.md`` suffix; the ``- description`` part
  is omitted when the concept has no description.
- Only the *root* ``index.md`` carries frontmatter, and it is exactly
  ``okf_version: "0.2"``. Subdirectory indexes are plain markdown.
- Log entries: ``* **Kind**: message`` under ``## YYYY-MM-DD`` headings,
  newest first (both headings and entries within a day).

No network calls; stdlib only.
"""

from __future__ import annotations

import re
from pathlib import Path

from okfsmith.core import frontmatter as _fm
from okfsmith.core.bundle import Bundle
from okfsmith.core.spec import OKF_VERSION, today_iso

#: Allowed ``log.md`` entry kinds.
LOG_KINDS = frozenset({"Creation", "Update", "Deprecation"})

_HEADING_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)


def _norm_subdir(subdir: str) -> str:
    return subdir.strip().strip("/")


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
    indexes are plain markdown. The file is written to disk, ``index_text`` is
    refreshed for the root index, and the path is returned.
    """
    subdir = _norm_subdir(subdir)
    index_dir = bundle.root if not subdir else bundle.root / subdir
    index_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{subdir}/" if subdir else ""

    entries: list[tuple[str, str]] = []  # (sort key, line)
    for concept in bundle.iter_concepts():
        if prefix and not concept.id.startswith(prefix):
            continue
        title = _title_for(concept.id, concept.frontmatter)
        link = concept.id[len(prefix) :] if prefix else concept.id
        description = str(concept.frontmatter.get("description") or "").strip()
        line = f"* [{title}]({link})"
        if description:
            line += f" - {description}"
        entries.append((title.casefold(), line))
    entries.sort(key=lambda item: item[0])

    heading = "# Index" if not subdir else f"# {subdir.rsplit('/', 1)[-1].title()}"
    body = heading + "\n\n" + "\n".join(line for _, line in entries) + "\n"
    if subdir:
        text = body
    else:
        text = _fm.serialize_frontmatter({"okf_version": OKF_VERSION}, body)

    index_path = index_dir / "index.md"
    index_path.write_text(text, encoding="utf-8")
    if not subdir:
        bundle.index_text = text
    return index_path


def append_log(
    bundle: Bundle, subdir: str = "", kind: str = "Update", message: str = ""
) -> Path:
    """Append an entry to ``log.md`` in *subdir*, newest-first.

    *kind* must be one of ``{"Creation", "Update", "Deprecation"}``
    (``ValueError`` otherwise). The entry goes under a ``## YYYY-MM-DD``
    heading for today (UTC); if no such heading exists yet it is created at
    the top of the file. Within a day, newer entries come first. The file is
    written to disk, ``log_text`` is refreshed for the root log, and the path
    is returned.
    """
    if kind not in LOG_KINDS:
        raise ValueError(f"kind must be one of {sorted(LOG_KINDS)}; got {kind!r}")
    subdir = _norm_subdir(subdir)
    log_dir = bundle.root if not subdir else bundle.root / subdir
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "log.md"

    today = today_iso()
    entry = f"* **{kind}**: {message.strip()}"

    existing = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
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

    log_path.write_text(text, encoding="utf-8")
    if not subdir:
        bundle.log_text = text
    return log_path
