"""Tier 1 PDF parsing via liteparse (run-llama/liteparse, Apache-2.0).

Verdict: liteparse IS installable from PyPI (checked 2026-09-26; latest
observed 2.14.7) and ships prebuilt wheels, so it is the Tier-1 PDF parser.
PyMuPDF is deliberately NOT used (AGPL); pypdf was the named fallback but is
not needed while liteparse is available.

Fully offline: constructed with ocr_enabled=False (upstream defaults to
selective OCR, which we must not trigger in Tier 1 — no network, no paid
APIs) and quiet=True. Tables come from liteparse's layout blocks
(extract_blocks=True), which detected real grid-aligned tables in testing.

Page text is post-processed into markdown-ish structure so downstream
sectioning can split PDFs the way it splits Markdown (external review
finding, fixed in 0.8.5): lines whose font size/weight marks them as
headings (from liteparse text items) are re-emitted as ATX ``#`` lines,
and hard-wrapped prose lines are joined back into paragraphs.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import ParsedDocument

import logging
from pathlib import Path

log = logging.getLogger(__name__)

try:
    from liteparse import LiteParse

    _LITEPARSE_AVAILABLE = True
except ImportError:  # pragma: no cover - handled gracefully at runtime
    LiteParse = None  # type: ignore
    _LITEPARSE_AVAILABLE = False


def _parser() -> LiteParse:
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


# ------------------------------------------------------------- structure --

_BOLD_FONT_RE = re.compile(r"bold", re.IGNORECASE)
_LIST_ITEM_RE = re.compile(r"^(?:[-*•·]|\d{1,3}[.)])\s")
_HEADING_MAX_CHARS = 120
# A prose line must reach this many characters before the next line is
# treated as its hard-wrapped continuation. Short lines (table cells,
# captions, labels) are complete units and are never merged.
_JOIN_MIN_LINE_CHARS = 40


def _heading_levels(items) -> dict[str, int]:
    """Map heading line text -> ATX level, from liteparse font structure.

    The body font size is the size carrying the most characters. Distinct
    larger sizes become heading levels (largest = level 1). Bold lines at
    body size also count (one level below the smallest size-based level)
    unless the document's body itself is predominantly bold. A line is
    only a heading candidate when it is short and does not end like a
    sentence fragment (``.``/``,``/``;``) — a bold lead-in inside a
    paragraph is not a heading.
    """
    sized: list[tuple[str, float, str]] = []
    for item in items or []:
        text = (getattr(item, "text", "") or "").strip()
        size = getattr(item, "font_size", None)
        if not text or not size:
            continue
        sized.append((text, float(size), getattr(item, "font_name", "") or ""))
    if not sized:
        return {}
    weights: dict[float, int] = {}
    for text, size, _font in sized:
        weights[size] = weights.get(size, 0) + len(text)
    body_size = max(weights, key=lambda s: weights[s])
    heading_sizes = sorted(
        {size for _t, size, _f in sized if size > body_size + 0.5}, reverse=True
    )
    level_of_size = {size: min(i + 1, 6) for i, size in enumerate(heading_sizes)}
    total_chars = sum(len(t) for t, _s, _f in sized)
    bold_chars = sum(
        len(t) for t, _s, f in sized if _BOLD_FONT_RE.search(f)
    )
    bold_is_body = total_chars > 0 and bold_chars > total_chars / 2
    bold_level = min(len(heading_sizes) + 1, 6)

    levels: dict[str, int] = {}
    for text, size, font in sized:
        if len(text) > _HEADING_MAX_CHARS or text.endswith((".", ",", ";")):
            continue
        level = level_of_size.get(size)
        if level is None and not bold_is_body:
            if size >= body_size - 0.5 and _BOLD_FONT_RE.search(font):
                level = bold_level
        if level is not None:
            levels[text] = min(levels.get(text, level), level)
    return levels


def _wrappable(line: str) -> bool:
    """True when *line* likely continues onto the next extracted line."""
    if line.endswith("-") and len(line) >= 2:
        return True  # hyphenated word split across lines
    return len(line) >= _JOIN_MIN_LINE_CHARS and not line.endswith(":")


def _join_wrapped(lines: list[str]) -> str:
    """Join hard-wrapped lines into one paragraph line."""
    out = lines[0]
    for nxt in lines[1:]:
        out += nxt if out.endswith("-") else " " + nxt
    return out


def _structured_text(page) -> str:
    """Rebuild a liteparse page's text with heading markers + paragraphs.

    Heading lines (per :func:`_heading_levels`) become ATX lines so the
    shared sectioning splits PDFs like Markdown; wrapped prose lines are
    joined; blank lines, list items, and short lines stay separate blocks.
    Falls back to the raw text when no structure is detectable.
    """
    raw = (getattr(page, "text", "") or "").strip()
    if not raw:
        return ""
    levels = _heading_levels(getattr(page, "text_items", None) or [])

    blocks: list[str] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            blocks.append(_join_wrapped(para))
            para.clear()

    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        level = levels.get(line)
        if level is not None:
            flush()
            blocks.append("#" * level + " " + line)
            continue
        if _LIST_ITEM_RE.match(line):
            flush()
            blocks.append(line)
            continue
        if para and not _wrappable(para[-1]):
            flush()
        para.append(line)
    flush()
    return "\n\n".join(blocks)


def parse_pdf(path: str | Path) -> ParsedDocument:
    """Parse a PDF into per-page text + tables.

    Pages with no text layer (no text items, no blocks, empty text) get
    needs_ocr=True so the router can escalate them to the OCR tier instead
    of emitting a textless stub.
    """
    from . import Page, ParsedDocument

    p = Path(path)
    parser = _parser()
    result = parser.parse(str(p))

    pages: list[Page] = []
    for pg in result.pages or []:
        number = int(getattr(pg, "page_num", len(pages) + 1) or len(pages) + 1)
        raw_text = (getattr(pg, "text", "") or "").strip()
        text = _structured_text(pg)
        tables = _blocks_to_tables(pg)
        text_items = getattr(pg, "text_items", None) or []
        has_text_layer = bool(raw_text) or bool(text_items) or bool(tables)
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
