"""Hand-crafted binary fixtures for parser tests (stdlib only, no heavy deps)."""

from __future__ import annotations

import zipfile
from pathlib import Path


# ---------------------------------------------------------------- PDF ------
def write_pdf(path: Path, pages: list[str]) -> Path:
    """Write a minimal PDF; each entry of *pages* is a content stream body."""
    objs: list[tuple[int, str]] = []
    kids = " ".join(f"{4 + i} 0 R" for i in range(len(pages)))
    objs.append((1, "<< /Type /Catalog /Pages 2 0 R >>"))
    objs.append((2, f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>"))
    objs.append((3, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"))
    for i, stream in enumerate(pages):
        objs.append(
            (
                4 + i,
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                "/Resources << /Font << /F1 3 0 R >> >> "
                f"/Contents {4 + len(pages) + i} 0 R >>",
            )
        )
    for i, stream in enumerate(pages):
        objs.append(
            (
                4 + len(pages) + i,
                f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
            )
        )
    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for n, body in objs:
        offsets[n] = len(out)
        out += f"{n} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for n in range(1, len(objs) + 1):
        out += f"{offsets[n]:010d} 00000 n \n".encode("latin-1")
    out += (
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF"
    ).encode("latin-1")
    path.write_bytes(bytes(out))
    return path


def text_stream(*lines: tuple[int, str]) -> str:
    """Build a content stream from (font_size, text) lines at descending y."""
    parts = []
    y = 720
    for size, text in lines:
        parts.append(f"BT /F1 {size} Tf 72 {y} Td ({text}) Tj ET")
        y -= 30
    return "\n".join(parts)


# --------------------------------------------------------------- DOCX ------
def write_docx(path: Path, heading: str, paragraphs: list[str],
               table: list[list[str]] | None = None) -> Path:
    """Minimal OOXML .docx: heading + paragraphs + optional table."""
    ct = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )

    def para(text: str, style: str | None = None) -> str:
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        return f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"

    body = para(heading, "Heading1")
    for ptext in paragraphs:
        body += para(ptext)
    if table:
        rows = ""
        for row in table:
            cells = "".join(
                f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in row
            )
            rows += f"<w:tr>{cells}</w:tr>"
        body += f"<w:tbl>{rows}</w:tbl>"
    doc = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", ct)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", doc)
    return path


# --------------------------------------------------------------- XLSX ------
def write_xlsx(path: Path, sheets: dict[str, list[list[str]]]) -> Path:
    """Minimal OOXML .xlsx with the given sheets (all cells inline strings)."""
    names = list(sheets)
    ct_overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(len(names))
    )
    ct = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        f"{ct_overrides}</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    )
    sheet_elems = "".join(
        f'<sheet name="{n}" sheetId="{i + 1}" r:id="rId{i + 1}"/>'
        for i, n in enumerate(names)
    )
    wb = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheet_elems}</sheets></workbook>"
    )
    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="rId{i + 1}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{i + 1}.xml"/>'
            for i in range(len(names))
        )
        + "</Relationships>"
    )

    def col_letter(i: int) -> str:
        s = ""
        i += 1
        while i:
            i, r = divmod(i - 1, 26)
            s = chr(65 + r) + s
        return s

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", ct)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("xl/workbook.xml", wb)
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        for i, name in enumerate(names):
            rows_xml = ""
            for r, row in enumerate(sheets[name], start=1):
                cells = "".join(
                    f'<c r="{col_letter(c)}{r}" t="inlineStr"><is><t>{v}</t></is></c>'
                    for c, v in enumerate(row)
                )
                rows_xml += f'<row r="{r}">{cells}</row>'
            sh = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f"<sheetData>{rows_xml}</sheetData></worksheet>"
            )
            zf.writestr(f"xl/worksheets/sheet{i + 1}.xml", sh)
    return path


# -------------------------------------------------------------- NOTION -----
NOTION_HASH = "a1b2c3d4e5f60718293a4b5c6d7e8f90"


def write_notion_export(path: Path) -> Path:
    """Notion-style export zip: one md page + _files assets + one CSV."""
    md_name = f"My Page {NOTION_HASH}.md"
    md_text = (
        "# My Page\n\n"
        "This is an exported Notion page with enough text to be meaningful. "
        "Original: https://www.notion.so/workspace/My-Page-1a2b3c4d5e6f\n\n"
        "## Details\n\n"
        "More detail text here about the page contents and structure.\n\n"
        "| A | B |\n|---|---|\n| 1 | 2 |\n"
    )
    files_dir = f"My Page {NOTION_HASH}_files"
    csv_name = f"Tasks {NOTION_HASH}.csv"
    csv_text = "Task,Owner\nDesign,Ada\nBuild,Bo\n"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(md_name, md_text)
        zf.writestr(f"{files_dir}/logo.png", b"\x89PNG\r\n\x1a\nfakepng")
        zf.writestr(csv_name, csv_text)
    return path
