"""Plain-text parsing with the stdlib only (no optional extras needed).

Covers ``.md`` / ``.markdown`` / ``.txt``: the file is read as UTF-8
(``errors="replace"`` so undecodable bytes never crash a run) and returned
as a single :class:`Page`. Markdown pipe tables are extracted into
``Page.tables`` via :func:`okfsmith.parsers.office.markdown_tables`, which
is a pure function and does not require MarkItDown.

This keeps the base install (no ``office`` extra) able to ingest the most
common knowledge sources: markdown notes and plain text.
"""

from __future__ import annotations

from pathlib import Path

from . import Page, ParsedDocument
from .office import markdown_tables


def parse_text_file(path: str | Path) -> ParsedDocument:
    """Read a markdown / plain-text file into a single-page ParsedDocument."""
    from . import _empty  # local import: avoid a cycle at module load

    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return _empty(f"{type(exc).__name__}: {exc}", p)
    page = Page(number=1, text=text, tables=markdown_tables(text))
    return ParsedDocument(
        pages=[page],
        meta={"source": str(p), "tier": "TIER1_LOCAL", "parser": "text"},
    )
