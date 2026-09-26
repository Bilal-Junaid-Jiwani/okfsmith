"""Notion export handler.

A Notion export is a zip containing per-page ``*.md`` files
(``<Title> <32-hex-hash>.md``), ``<Title> <hash>_files/`` asset directories,
and ``*.csv`` files for per-database exports.

Each Notion page maps to one ParsedDocument (single page), with
``meta["resource"]`` set to the original notion.so URL when the export
carries one. ``parse_notion_zip_as_document`` merges those into the single
ParsedDocument that :func:`okfsmith.parsers.parse_file` must return.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import ParsedDocument

import logging
import re
import tempfile
import zipfile
from pathlib import Path

from .ziputil import safe_extract

log = logging.getLogger(__name__)

_NOTION_URL_RE = re.compile(r"https?://(?:www\.)?notion\.so/[^\s)>\]]+")
_HASH_SUFFIX_RE = re.compile(r"\s+[0-9a-f]{32}$")


def looks_like_notion_export(zip_path: str | Path) -> bool:
    """Heuristic: zip with Notion-style page markdowns and ``_files`` dirs."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile:
        return False
    md_files = [n for n in names if n.lower().endswith(".md")]
    files_dirs = [n for n in names if "_files/" in n or n.endswith("_files")]
    return bool(md_files) and bool(files_dirs)


def notion_page_title(md_name: str) -> str:
    """'My Page a1b2...32hex.md' -> 'My Page'."""
    stem = Path(md_name).stem
    return _HASH_SUFFIX_RE.sub("", stem).strip() or stem


def notion_resource_url(md_text: str) -> str | None:
    """Original notion.so URL, if the export metadata carries one."""
    m = _NOTION_URL_RE.search(md_text or "")
    return m.group(0) if m else None


def _page_from_markdown_file(md_path: Path, title: str) -> ParsedDocument:
    from . import Page, ParsedDocument
    from .office import markdown_tables

    text = md_path.read_text(encoding="utf-8", errors="replace").strip()
    url = notion_resource_url(text)
    page = Page(number=1, text=text, tables=markdown_tables(text))
    meta: dict = {
        "source": str(md_path),
        "tier": "TIER1_LOCAL",
        "parser": "notion",
        "notion": True,
        "notion_title": title,
    }
    if url:
        meta["resource"] = url
    assets_dir = md_path.parent / f"{md_path.stem}_files"
    if assets_dir.is_dir():
        meta["assets"] = sorted(
            p.name for p in assets_dir.iterdir() if p.is_file()
        )
    return ParsedDocument(pages=[page], meta=meta)


def _page_from_csv_file(csv_path: Path, title: str) -> ParsedDocument:
    from . import office  # reuse the deterministic CSV parser via public API

    doc = office.parse_office(csv_path)
    doc.meta.update({"parser": "notion", "notion": True, "notion_title": title})
    return doc


def parse_notion_export(zip_path: str | Path) -> list[ParsedDocument]:
    """Unzip a Notion export; return one ParsedDocument per Notion page.

    Markdown pages and per-database CSVs each become a ParsedDocument.
    ``_files/`` asset directories are recorded in meta, not parsed.
    """
    p = Path(zip_path)
    docs: list = []
    with tempfile.TemporaryDirectory(prefix="okfsmith-notion-") as tmp:
        with zipfile.ZipFile(p) as zf:
            safe_extract(zf, tmp)
        root = Path(tmp)
        md_files = sorted(
            f
            for f in root.rglob("*.md")
            if "_files" not in f.parts and not f.name.startswith(".")
        )
        csv_files = sorted(
            f
            for f in root.rglob("*.csv")
            if "_files" not in f.parts and not f.name.startswith(".")
        )
        for md in md_files:
            title = notion_page_title(md.name)
            try:
                docs.append(_page_from_markdown_file(md, title))
            except Exception as exc:
                log.warning("notion page %s skipped: %s", md.name, exc)
        for cf in csv_files:
            title = notion_page_title(cf.name)
            try:
                docs.append(_page_from_csv_file(cf, title))
            except Exception as exc:
                log.warning("notion csv %s skipped: %s", cf.name, exc)
    return docs


def parse_notion_zip_as_document(zip_path: str | Path) -> ParsedDocument:
    """Merge a Notion export's per-page documents into one ParsedDocument."""
    from . import ParsedDocument

    p = Path(zip_path)
    per_page = parse_notion_export(p)
    pages: list = []
    index: list[dict] = []
    for doc in per_page:
        pg = doc.pages[0]
        pg.number = len(pages) + 1
        pages.append(pg)
        index.append(
            {
                "title": doc.meta.get("notion_title"),
                "resource": doc.meta.get("resource"),
                "assets": doc.meta.get("assets", []),
            }
        )
    return ParsedDocument(
        pages=pages,
        meta={
            "source": str(p),
            "tier": "TIER1_LOCAL",
            "parser": "notion",
            "notion": True,
            "notion_pages": index,
        },
    )


__all__ = [
    "looks_like_notion_export",
    "notion_page_title",
    "notion_resource_url",
    "parse_notion_export",
    "parse_notion_zip_as_document",
]
