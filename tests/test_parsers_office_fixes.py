"""Regression tests for QA findings in the office/zip parsers.

Covers:
- generic-zip member dispatch: ``.txt``/``.md``/``.csv`` members go through
  the Tier-1 stdlib parsers, not MarkItDown (the genuine
  ``test_generic_zip_members`` product bug);
- H6: nested zips recurse to depth 1, per the module docstring's promise;
- L18: repeated member names are deduped deterministically, and symlink
  members are skipped instead of ingesting their raw target text.
"""

import io
import logging
import stat
import zipfile
from pathlib import Path

from okfsmith.parsers import parse_file
from okfsmith.parsers.office import parse_office


def _make_zip(path: Path, members: dict) -> Path:
    """Write *members* (name -> bytes) into a zip at *path*."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


def test_zip_text_members_use_stdlib_parsers(tmp_path: Path):
    """txt members are text-parsed; csv members use the stdlib CSV parser.

    This environment has no ``office`` extra installed, so extracted content
    proves the Tier-1 parsers were used instead of MarkItDown.
    """
    zf = _make_zip(
        tmp_path / "bundle.zip",
        {
            "a.txt": b"alpha content here",
            "c.csv": b"x,y\n1,2\n",
        },
    )
    doc = parse_file(zf)
    assert doc.meta["parser"] == "zip"
    assert len(doc.pages) == 2
    texts = [p.text for p in doc.pages]
    assert any("alpha content here" in t for t in texts)
    assert any("1" in t and "2" in t for t in texts)
    # member labels survive
    assert any(t.startswith("[a.txt]") for t in texts)
    assert any(t.startswith("[c.csv]") for t in texts)
    # text content is never routed to the OCR tier
    assert all(p.needs_ocr is False for p in doc.pages)


def test_zip_md_member_dispatched_to_text_parser(tmp_path: Path):
    """md/txt members of a zip go through the stdlib text parser.

    Called via parse_office directly: parse_file routes md-containing zips
    to the Notion parser, but the office zip dispatcher itself must still
    send text members to parsers.text rather than MarkItDown.
    """
    zf = _make_zip(
        tmp_path / "t.zip",
        {
            "doc.md": b"# T\n\n| a | b |\n|---|---|\n| 1 | 2 |\n",
            "n.txt": b"plain text member",
        },
    )
    doc = parse_office(zf)
    assert doc.meta["parser"] == "zip"
    assert len(doc.pages) == 2
    texts = [p.text for p in doc.pages]
    assert any("plain text member" in t for t in texts)
    md_page = next(p for p in doc.pages if p.text.startswith("[doc.md]"))
    assert md_page.tables == [[["a", "b"], ["1", "2"]]]
    assert all(p.needs_ocr is False for p in doc.pages)


def test_nested_zip_recursed_to_depth_1(tmp_path: Path):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("data.csv", "a,b\n1,2\n")
        zf.writestr("note.txt", "inner text content")
    outer = _make_zip(
        tmp_path / "outer.zip",
        {"top.txt": b"top level text", "inner.zip": inner.getvalue()},
    )
    doc = parse_file(outer)
    texts = [p.text for p in doc.pages]
    assert len(doc.pages) == 3
    assert any("top level text" in t for t in texts)
    assert any("inner text content" in t for t in texts)
    assert any("1" in t and "2" in t for t in texts)
    # nested members are labeled with their path inside the outer zip
    assert any(t.startswith("[inner.zip/data.csv]") for t in texts)
    assert any(t.startswith("[inner.zip/note.txt]") for t in texts)


def test_nested_zip_below_depth_1_skipped_with_warning(tmp_path: Path, caplog):
    deep = io.BytesIO()
    with zipfile.ZipFile(deep, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("deep.txt", "too deep content")
    mid = io.BytesIO()
    with zipfile.ZipFile(mid, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mid.txt", "mid level content")
        zf.writestr("deep.zip", deep.getvalue())
    outer = _make_zip(tmp_path / "outer.zip", {"mid.zip": mid.getvalue()})
    with caplog.at_level(logging.WARNING, logger="okfsmith.parsers.office"):
        doc = parse_file(outer)
    texts = [p.text for p in doc.pages]
    assert any("mid level content" in t for t in texts)
    assert not any("too deep content" in t for t in texts)
    assert any("below depth limit" in r.message for r in caplog.records)


def test_duplicate_member_names_deduped_deterministically(tmp_path: Path, caplog):
    zf = tmp_path / "dups.zip"
    with zipfile.ZipFile(zf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("dup.txt", "first occurrence")
        z.writestr("other.txt", "other content")
        z.writestr("dup.txt", "second occurrence")
    with caplog.at_level(logging.WARNING, logger="okfsmith.parsers.ziputil"):
        doc = parse_file(zf)
    dup_pages = [p for p in doc.pages if p.text.startswith("[dup.txt]")]
    assert len(dup_pages) == 1
    # last occurrence wins (documented, matches zipfile's name lookup)
    assert "second occurrence" in dup_pages[0].text
    assert "first occurrence" not in dup_pages[0].text
    assert any("duplicate zip member" in r.message for r in caplog.records)
    # deterministic: same archive parses identically every time
    doc2 = parse_file(zf)
    assert [p.text for p in doc2.pages] == [p.text for p in doc.pages]


def test_symlink_member_not_ingested_as_content(tmp_path: Path, caplog):
    zf = tmp_path / "link.zip"
    link_info = zipfile.ZipInfo("evil.txt")
    link_info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(zf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("ok.txt", "legit content")
        z.writestr(link_info, "/etc/passwd")
    with caplog.at_level(logging.WARNING, logger="okfsmith.parsers.ziputil"):
        doc = parse_file(zf)
    texts = [p.text for p in doc.pages]
    assert any("legit content" in t for t in texts)
    assert not any("/etc/passwd" in t for t in texts)
    assert not any("evil.txt" in t for t in texts)
    assert any("symlink" in r.message for r in caplog.records)
