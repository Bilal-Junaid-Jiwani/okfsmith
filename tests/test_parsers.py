"""Tests for okfsmith.parsers: tiered, free-first document parsing.

Fixtures are hand-crafted with stdlib only (see tests/_helpers.py):
no heavy writer dependencies, no network.
"""

import hashlib
import importlib.util
import logging
import warnings
import zipfile
from pathlib import Path

import pytest

from okfsmith.core.bundle import Bundle
from okfsmith.parsers import (
    Page,
    ParsedDocument,
    dedup,
    notion,
    parse_file,
    router,
    sectioning,
)
from okfsmith.parsers.ingest_no_llm import DESCRIPTION, GENERATED_BY, ingest_no_llm
from okfsmith.parsers.router import Tier
from tests._helpers import (
    NOTION_HASH,
    text_stream,
    write_docx,
    write_notion_export,
    write_pdf,
    write_xlsx,
)

LONG_TEXT = ("Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 40).strip()


# ------------------------------------------------------------ pdf ------
def test_pdf_two_pages(tmp_path: Path):
    pdf = write_pdf(
        tmp_path / "two.pdf",
        [
            text_stream((24, "Report Title"), (12, "Page one has some text.")),
            text_stream((24, "Second Page"), (12, "More text on page two.")),
        ],
    )
    doc = parse_file(pdf)
    assert len(doc.pages) == 2
    assert doc.pages[0].number == 1
    assert "Report Title" in doc.pages[0].text
    assert "Second Page" in doc.pages[1].text
    assert all(not pg.needs_ocr for pg in doc.pages)
    assert doc.meta["parser"] == "liteparse"
    assert doc.meta["tier"] == "TIER1_LOCAL"


def test_pdf_table_extracted(tmp_path: Path):
    rows = [("Name", "Qty", "Price"), ("Apples", "10", "2.50"), ("Oranges", "5", "3.00")]
    parts = []
    y = 700
    for name, qty, price in rows:
        parts.append(f"BT /F1 12 Tf 72 {y} Td ({name}) Tj ET")
        parts.append(f"BT /F1 12 Tf 220 {y} Td ({qty}) Tj ET")
        parts.append(f"BT /F1 12 Tf 320 {y} Td ({price}) Tj ET")
        y -= 20
    pdf = write_pdf(tmp_path / "table.pdf", ["\n".join(parts)])
    doc = parse_file(pdf)
    assert len(doc.pages) == 1
    tables = doc.pages[0].tables
    assert tables, "expected at least one table from layout blocks"
    flat = [cell for row in tables[0] for cell in row]
    assert "Name" in flat and "Apples" in flat and "2.50" in flat


def test_pdf_scanned_page_needs_ocr(tmp_path: Path):
    # Vector rectangle only, no text operators -> no text layer.
    pdf = write_pdf(tmp_path / "scanned.pdf", ["0 0 100 100 re S"])
    doc = parse_file(pdf)
    assert len(doc.pages) == 1
    assert doc.pages[0].text == ""
    assert doc.pages[0].needs_ocr is True


def test_corrupt_pdf_warns_and_skips(tmp_path: Path, caplog):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"this is not a pdf at all \x00\x01\x02")
    # M27: the skip notice goes through logging only — no warnings.warn, so
    # no RuntimeWarning and no caller file:line leaked onto stderr.
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any warning becomes an error
        with caplog.at_level(logging.WARNING, logger="okfsmith.parsers"):
            doc = parse_file(bad)
    assert doc.pages == []
    assert "error" in doc.meta
    skipping = [
        r for r in caplog.records
        if r.name == "okfsmith.parsers" and "skipping" in r.getMessage()
    ]
    assert any("bad.pdf" in r.getMessage() for r in skipping)


def test_missing_file_skips(tmp_path: Path):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        doc = parse_file(tmp_path / "nope.pdf")
    assert doc.pages == [] and "error" in doc.meta


# ---------------------------------------------------------- office ------
# Office-format parsing needs the `office` extra (MarkItDown). CI's base
# install only has `[test]`, so these genuinely cannot run there — skip
# with a clear reason instead of failing on the graceful-degradation path.
requires_office = pytest.mark.skipif(
    importlib.util.find_spec("markitdown") is None,
    reason="office extra not installed",
)


@requires_office
def test_docx_heading_and_table(tmp_path: Path):
    docx = write_docx(
        tmp_path / "notes.docx",
        "Project Notes",
        ["Kickoff went well. " * 30],
        table=[["Task", "Owner"], ["Design", "Ada"]],
    )
    doc = parse_file(docx)
    assert len(doc.pages) == 1
    assert "Project Notes" in doc.pages[0].text
    assert any(
        ["Task", "Owner"] == row[:2]
        for table in doc.pages[0].tables
        for row in table
    ), doc.pages[0].tables


@requires_office
def test_xlsx_per_sheet_pages(tmp_path: Path):
    xlsx = write_xlsx(
        tmp_path / "data.xlsx",
        {"Sheet1": [["Name", "Qty"], ["Apples", "10"]], "Sheet2": [["X"], ["1"]]},
    )
    doc = parse_file(xlsx)
    assert len(doc.pages) == 2
    assert doc.pages[0].tables[0][0][:2] == ["Name", "Qty"]
    assert doc.pages[1].tables[0][0] == ["X"]
    assert all(not pg.needs_ocr for pg in doc.pages)


def test_txt_and_md(tmp_path: Path):
    txt = tmp_path / "hello.txt"
    txt.write_text("# Hello\n\nSome text here.")
    doc = parse_file(txt)
    assert "Hello" in doc.pages[0].text

    md = tmp_path / "doc.md"
    md.write_text("# Title\n\n| A | B |\n|---|---|\n| 1 | 2 |\n")
    doc = parse_file(md)
    assert doc.pages[0].tables[0][0] == ["A", "B"]


def test_generic_zip_members(tmp_path: Path):
    (tmp_path / "a.txt").write_text("alpha content here")
    zf = tmp_path / "bundle.zip"
    with zipfile.ZipFile(zf, "w") as z:
        z.write(tmp_path / "a.txt", "a.txt")
    doc = parse_file(zf)
    assert len(doc.pages) == 1
    assert "alpha content here" in doc.pages[0].text


def test_image_flagged_for_ocr(tmp_path: Path):
    img = tmp_path / "photo.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    doc = parse_file(img)
    assert len(doc.pages) == 1
    assert doc.pages[0].needs_ocr is True
    assert doc.pages[0].text == ""  # no textless stub content emitted


# ---------------------------------------------------------- notion ------
def test_notion_export(tmp_path: Path):
    zf = write_notion_export(tmp_path / "export.zip")
    assert notion.looks_like_notion_export(zf)

    doc = parse_file(zf)
    assert doc.meta.get("notion") is True
    assert len(doc.pages) == 2  # one md page + one CSV database export

    index = doc.meta["notion_pages"]
    md_entry = next(e for e in index if e["title"] == "My Page")
    assert md_entry["resource"] == "https://www.notion.so/workspace/My-Page-1a2b3c4d5e6f"
    assert md_entry["assets"] == ["logo.png"]

    csv_page = doc.pages[[e["title"] for e in index].index("Tasks")]
    assert csv_page.tables[0][0] == ["Task", "Owner"]

    assert notion.notion_page_title(f"My Page {NOTION_HASH}.md") == "My Page"


def test_notion_url_absent_is_none():
    assert notion.notion_resource_url("no links here") is None


# ---------------------------------------------------------- router ------
def test_route_defaults_tier1():
    assert router.route("report.pdf") is Tier.TIER1_LOCAL
    assert router.route("notes.docx") is Tier.TIER1_LOCAL
    assert router.route("export.zip") is Tier.TIER1_LOCAL


def test_route_image_tier3():
    assert router.route("scan.png") is Tier.TIER3_OCR
    assert router.route("photo.JPG") is Tier.TIER3_OCR


def test_ocr_escalations_message():
    parsed = ParsedDocument(
        pages=[
            Page(number=1, text="hello", tables=[], needs_ocr=False),
            Page(number=2, text="", tables=[], needs_ocr=True),
        ],
        meta={"source": "scan.pdf"},
    )
    msgs = router.ocr_escalations(parsed)
    assert len(msgs) == 1
    assert msgs[0] == (
        "scan.pdf: page 2 has no text layer — needs OCR tier "
        "(llamaparse/mistral/azure); skipping OCR in v1"
    )


# ------------------------------------------------------- sectioning ------
def _doc(text: str, pages: int = 1) -> ParsedDocument:
    per = [Page(number=i + 1, text=text, tables=[]) for i in range(pages)]
    return ParsedDocument(pages=per, meta={})


def test_sectioning_headings_and_code_blocks():
    text = (
        "# Alpha\n\nIntro text.\n\n"
        "```python\n# not a heading\nx = 1\n```\n\n"
        "## Beta\n\nBody of beta.\n\n"
        "### Gamma\n\nDeep text.\n"
    )
    doc = _doc(text + LONG_TEXT)
    result = sectioning.section(doc)
    assert not result.too_small
    titles = [(s.title, s.level) for s in result.sections]
    assert titles == [("Alpha", 1), ("Beta", 2), ("Gamma", 3)]
    assert "# not a heading" in result.sections[0].text  # fence kept, not split
    assert result.sections[0].page_span == (1, 1)


def test_sectioning_tables_attached_and_page_span():
    pages = [
        Page(number=1, text="# One\n\nfirst", tables=[[["a"]]]),
        Page(number=2, text="# Two\n\nsecond", tables=[]),
    ]
    result = sectioning.section(ParsedDocument(pages=pages, meta={}))
    assert result.sections[0].tables == [[["a"]]]
    assert result.sections[0].page_span == (1, 1)
    assert result.sections[1].page_span == (2, 2)


def test_sectioning_too_small():
    result = sectioning.section(_doc("# Tiny\n\nshort"))
    assert result.too_small is True


def test_sectioning_no_headings_single_section():
    result = sectioning.section(_doc("Just prose.\n" + LONG_TEXT))
    assert len(result.sections) == 1
    assert result.sections[0].level == 0


# ------------------------------------------------------ ingest_no_llm ------
def _big_doc() -> ParsedDocument:
    text = f"# Alpha\n\n{LONG_TEXT}\n\n## Beta\n\n{LONG_TEXT}\n"
    return ParsedDocument(
        pages=[Page(number=1, text=text, tables=[])],
        meta={"source": "notes.docx"},
    )


def test_ingest_no_llm_draft_shape(tmp_path: Path):
    bundle = Bundle(tmp_path / "bundle")
    ids = ingest_no_llm(bundle, _big_doc(), "notes.docx")
    assert len(ids) == 2

    concept = bundle.get(ids[0])
    assert concept is not None
    fm = concept.frontmatter
    assert fm["type"] == "Draft"
    assert fm["status"] == "draft"
    assert fm["tags"] == ["draft", "no-llm"]
    assert fm["description"] == DESCRIPTION
    assert fm["resource"] == "notes.docx"
    assert fm["generated"]["by"] == GENERATED_BY
    assert fm["generated"]["at"]  # ISO timestamp present
    assert fm["title"] == "Alpha"
    assert len(concept.body) > 0

    # second section got its own concept, ids are unique
    assert ids[0] != ids[1]
    assert bundle.get(ids[1]).frontmatter["title"] == "Beta"


def test_ingest_no_llm_too_small_creates_nothing(tmp_path: Path):
    bundle = Bundle(tmp_path / "bundle")
    assert ingest_no_llm(bundle, _doc("# Tiny\n\nshort"), "tiny.txt") == []
    assert list(bundle.iter_concepts()) == []


def test_ingest_no_llm_skips_ocr_pages(tmp_path: Path):
    bundle = Bundle(tmp_path / "bundle")
    parsed = ParsedDocument(
        pages=[
            Page(number=1, text=f"# Real\n\n{LONG_TEXT}", tables=[], needs_ocr=False),
            Page(number=2, text="", tables=[], needs_ocr=True),
        ],
        meta={"source": "scan.pdf"},
    )
    ids = ingest_no_llm(bundle, parsed, "scan.pdf")
    assert len(ids) == 1  # only the born-digital section; no textless stub
    assert bundle.get(ids[0]).frontmatter["title"] == "Real"


def test_ingest_no_llm_parse_error_creates_nothing(tmp_path: Path):
    bundle = Bundle(tmp_path / "bundle")
    parsed = ParsedDocument(pages=[], meta={"error": "boom"})
    assert ingest_no_llm(bundle, parsed, "bad.pdf") == []


# ------------------------------------------------------------ dedup ------
def test_sha256_of(tmp_path: Path):
    f = tmp_path / "f.bin"
    f.write_bytes(b"abc123")
    assert dedup.sha256_of(f) == hashlib.sha256(b"abc123").hexdigest()


def test_manifest_dedup_roundtrip(tmp_path: Path):
    bundle = Bundle(tmp_path / "bundle")
    digest = "0" * 64
    assert dedup.already_ingested(bundle, digest) is False
    dedup.record_ingested(bundle, digest, "notes.docx")
    assert dedup.already_ingested(bundle, digest) is True
    mp = tmp_path / "bundle" / ".okfsmith" / "manifest.json"
    assert mp.exists()
    assert not dedup.already_ingested(bundle, "1" * 64)


def test_manifest_corrupt_is_empty(tmp_path: Path):
    bundle = Bundle(tmp_path / "bundle")
    mp = dedup.manifest_path(bundle)
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text("{not json")
    assert dedup.load_manifest(bundle) == {}
    assert dedup.already_ingested(bundle, "0" * 64) is False


def test_txt_and_md_parse_without_office_extra(tmp_path: Path, monkeypatch):
    """Regression: moving MarkItDown to the `office` extra must not break
    .md/.txt ingestion on a base install. Simulate 'markitdown not
    installed' and prove the stdlib text parser still handles them."""
    import sys

    monkeypatch.setitem(sys.modules, "markitdown", None)

    md = tmp_path / "notes.md"
    md.write_text("# Title\n\nSome body text.\n")
    doc = parse_file(md)
    assert not doc.meta.get("error"), doc.meta
    assert "Title" in doc.pages[0].text

    txt = tmp_path / "notes.txt"
    txt.write_text("plain text body")
    doc = parse_file(txt)
    assert not doc.meta.get("error"), doc.meta
    assert "plain text body" in doc.pages[0].text

    # ... but office formats still degrade gracefully without the extra.
    from tests._helpers import write_docx

    docx = write_docx(tmp_path / "doc.docx", "H", ["para"])
    doc = parse_file(docx)
    assert "markitdown is not installed" in doc.meta.get("error", "")
