"""Tiered, free-first document parsing for okfsmith.

Public surface:
    parse_file(path) -> ParsedDocument

Routing by file type:
    *.pdf          -> parsers.pdf        (Tier 1, liteparse, fully offline)
    *.md/*.txt     -> parsers.text       (Tier 1, stdlib only, fully offline)
    notion exports -> parsers.notion     (zip that looks like a Notion export)
    everything else handled formats
                   -> parsers.office    (MarkItDown: docx/pptx/xlsx/html/csv/zip/images;
                                         requires the ``office`` extra)

Graceful degradation: a corrupt or unreadable file never crashes the run.
parse_file catches parser exceptions, logs a warning, and returns an empty
ParsedDocument with meta["error"] set so the caller can skip it.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class Page:
    """One parsed page of a document."""

    number: int                      # 1-based page number
    text: str                        # extracted text (markdown-ish where available)
    tables: list[list[list[str]]] = field(default_factory=list)  # tables on the page
    needs_ocr: bool = False          # True when the page has no text layer (image-only)


@dataclass
class ParsedDocument:
    """Result of parsing one source file."""

    pages: list[Page] = field(default_factory=list)
    meta: dict = field(default_factory=dict)   # source, tier, error, notion, ...


def _empty(reason: str, source: Path) -> ParsedDocument:
    return ParsedDocument(pages=[], meta={"source": str(source), "error": reason})


def parse_file(path: str | Path) -> ParsedDocument:
    """Parse *path* into a ParsedDocument. Never raises on corrupt input.

    Returns an empty ParsedDocument with meta["error"] set when the file
    cannot be parsed, so callers can warn-and-skip instead of crashing.
    """
    from . import notion, office, pdf, text  # local imports: keep import cost lazy

    p = Path(path)
    try:
        if not p.exists() or not p.is_file():
            raise FileNotFoundError(f"no such file: {p}")
        suffix = p.suffix.lower()

        if suffix == ".pdf":
            return pdf.parse_pdf(p)
        if suffix in {".md", ".markdown", ".txt"}:
            return text.parse_text_file(p)
        if suffix == ".zip" and notion.looks_like_notion_export(p):
            return notion.parse_notion_zip_as_document(p)
        return office.parse_office(p)
    except Exception as exc:  # graceful degradation: warn + skip, never crash
        msg = f"skipping {p.name}: could not parse ({type(exc).__name__}: {exc})"
        log.warning(msg)
        warnings.warn(msg, RuntimeWarning, stacklevel=2)
        return _empty(f"{type(exc).__name__}: {exc}", p)


__all__ = ["Page", "ParsedDocument", "parse_file"]
