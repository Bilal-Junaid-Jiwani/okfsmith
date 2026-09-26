"""Tier 1 PDF parsing via liteparse (run-llama/liteparse, Apache-2.0).

Verdict: liteparse IS installable from PyPI (checked 2026-09-26; latest
observed 2.14.7) and ships prebuilt wheels, so it is the Tier-1 PDF parser.
PyMuPDF is deliberately NOT used (AGPL); pypdf was the named fallback but is
not needed while liteparse is available.

Fully offline: constructed with ocr_enabled=False (upstream defaults to
selective OCR, which we must not trigger in Tier 1 — no network, no paid
APIs) and quiet=True. Tables come from liteparse's layout blocks
(extract_blocks=True), which detected real grid-aligned tables in testing.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

try:
    from liteparse import LiteParse

    _LITEPARSE_AVAILABLE = True
except ImportError:  # pragma: no cover - handled gracefully at runtime
    LiteParse = None  # type: ignore
    _LITEPARSE_AVAILABLE = False


def _parser() -> "LiteParse":
    if not _LITEPARSE_AVAILABLE:
        raise RuntimeError(
            "liteparse is not installed; install the 'okfsmith' package with "
            "its PDF extras to parse PDFs"
        )
    # Tier 1 is fully offline: OCR disabled, no servers, no network calls.
    return LiteParse(ocr_enabled=False, quiet=True, extract_blocks=True)


def _blocks_to_tables(page) -> list[list[list[str]]]:
    """Convert liteparse layout blocks of kind 'table' to row lists."""
    tables: list[list[list[str]]] = []
    blocks = getattr(page, "blocks", None) or []
    for block in blocks:
        if getattr(block, "kind", "") != "table":
            continue
        rows = getattr(block, "rows", None) or []
        table: list[list[str]] = []
        for row in rows:
            table.append([getattr(cell, "text", "") or "" for cell in row])
        if table:
            tables.append(table)
    return tables


def parse_pdf(path: str | Path) -> "ParsedDocument":
    """Parse a PDF into per-page text + tables.

    Pages with no text layer (no text items, no blocks, empty text) get
    needs_ocr=True so the router can escalate them to the OCR tier instead
    of emitting a textless stub.
    """
    from . import ParsedDocument, Page

    p = Path(path)
    parser = _parser()
    result = parser.parse(str(p))

    pages: list[Page] = []
    for pg in result.pages or []:
        number = int(getattr(pg, "page_num", len(pages) + 1) or len(pages) + 1)
        text = (getattr(pg, "text", "") or "").strip()
        tables = _blocks_to_tables(pg)
        text_items = getattr(pg, "text_items", None) or []
        has_text_layer = bool(text) or bool(text_items) or bool(tables)
        pages.append(
            Page(
                number=number,
                text=text,
                tables=tables,
                needs_ocr=not has_text_layer,
            )
        )

    if not pages:
        log.warning("pdf %s: no pages extracted (empty or unreadable)", p.name)

    return ParsedDocument(
        pages=pages,
        meta={"source": str(p), "tier": "TIER1_LOCAL", "parser": "liteparse"},
    )
