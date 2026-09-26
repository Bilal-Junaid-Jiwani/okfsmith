"""Deterministic, no-LLM sectioning.

Splits parsed pages into a heading hierarchy (ATX ``#``-style headings;
``#`` inside fenced code blocks never splits), keeping fenced code blocks
and tables attached to their section. Each section records the 1-based page
span it came from.

Sources whose total text is under 1000 characters are marked
``too_small=True`` so downstream ingest defers entity creation instead of
emitting stub concepts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TOO_SMALL_CHARS = 1000

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


@dataclass
class Section:
    title: str
    level: int                       # 1..6 for headings; 0 = unheaded preamble
    text: str                        # body text (heading line excluded)
    page_span: tuple[int, int]       # (first_page, last_page), 1-based
    tables: list[list[list[str]]] = field(default_factory=list)


@dataclass
class DocumentSections:
    sections: list[Section]
    too_small: bool                  # True -> defer entity creation


@dataclass
class _OpenSection:
    title: str
    level: int
    lines: list[str]
    pages: set[int]


def _flush(open_sec: _OpenSection | None, out: list[Section]) -> None:
    if open_sec is None or (not open_sec.lines and open_sec.level == 0):
        return
    pages = sorted(open_sec.pages)
    span = (pages[0], pages[-1]) if pages else (0, 0)
    out.append(
        Section(
            title=open_sec.title,
            level=open_sec.level,
            text="\n".join(open_sec.lines).strip(),
            page_span=span,
            tables=[],
        )
    )


def section(parsed) -> DocumentSections:
    """Split a ParsedDocument into sections."""
    pages = list(parsed.pages or [])
    total_chars = sum(len(p.text or "") for p in pages)

    # Flatten to (page_number, line) pairs, tracking fenced code blocks.
    lines: list[tuple[int, str]] = []
    for pg in pages:
        for line in (pg.text or "").splitlines():
            lines.append((pg.number, line))

    sections: list[Section] = []
    current: _OpenSection | None = None
    in_fence = False

    def new_section(title: str, level: int, page: int) -> None:
        nonlocal current
        _flush(current, sections)
        current = _OpenSection(title=title, level=level, lines=[], pages={page})

    for page_no, line in lines:
        fence = _FENCE_RE.match(line)
        if fence:
            in_fence = not in_fence
        heading = _HEADING_RE.match(line) if not in_fence else None
        if heading:
            new_section(heading.group(2).strip(), len(heading.group(1)), page_no)
            continue
        if current is None:
            # Preamble before any heading.
            first = next((ln for _, ln in lines if ln.strip()), "")
            new_section(first.strip()[:80] or "Untitled", 0, page_no)
        current.lines.append(line)
        current.pages.add(page_no)

    _flush(current, sections)

    # Attach each page's tables to the first section touching that page.
    page_tables = {pg.number: list(pg.tables or []) for pg in pages}
    for page_no, tables in page_tables.items():
        if not tables:
            continue
        for sec in sections:
            if sec.page_span[0] <= page_no <= sec.page_span[1]:
                sec.tables.extend(tables)
                break

    return DocumentSections(
        sections=sections,
        too_small=total_chars < TOO_SMALL_CHARS,
    )


__all__ = ["Section", "DocumentSections", "section", "TOO_SMALL_CHARS"]
