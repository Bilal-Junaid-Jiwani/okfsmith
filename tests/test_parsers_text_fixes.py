"""Regression tests for QA fixes in okfsmith.parsers.text.

C5  - UTF-16 input (with/without BOM) decodes properly; no NUL garbage.
M9  - UTF-8 BOM is stripped (no garbage first character, headings detected).
M10 - latin-1-ish input decodes via a windows-1252 fallback with a logged
      warning; never silent U+FFFD replacement characters.
M11 - binary input raises BinaryContentError (a clean, catchable error);
      parse_file() maps it to a warn-and-skip empty document.
M3  - YAML frontmatter is stripped from markdown sources before sectioning;
      it must not become a body section.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from okfsmith.parsers import parse_file
from okfsmith.parsers.sectioning import section
from okfsmith.parsers.text import BinaryContentError, parse_text_file

# ------------------------------------------------------------------ C5 ---


def test_utf16_with_bom_decodes(tmp_path: Path):
    body = "# Hello\n\n" + "word " * 300
    p = tmp_path / "u16.md"
    p.write_bytes(body.encode("utf-16"))  # writes the BOM
    doc = parse_file(p)
    assert not doc.meta.get("error"), doc.meta
    text = doc.pages[0].text
    assert text == body
    assert "\x00" not in text


def test_utf16_without_bom_decodes(tmp_path: Path):
    body = "# Hello\n\nCaf\u00e9 content here.\n"
    for codec, name in (("utf-16-le", "le"), ("utf-16-be", "be")):
        p = tmp_path / f"u16nb-{name}.md"
        p.write_bytes(body.encode(codec))  # no BOM
        doc = parse_file(p)
        assert not doc.meta.get("error"), (name, doc.meta)
        assert doc.pages[0].text == body, name
        assert "\x00" not in doc.pages[0].text


def test_utf16_sections_cleanly(tmp_path: Path):
    p = tmp_path / "u16sec.md"
    p.write_bytes(("# Hello\n\n" + "word " * 300).encode("utf-16"))
    secs = section(parse_file(p)).sections
    assert [(s.title, s.level) for s in secs] == [("Hello", 1)]


# ------------------------------------------------------------------ M9 ---


def test_utf8_bom_stripped(tmp_path: Path):
    p = tmp_path / "bom.md"
    p.write_bytes(b"\xef\xbb\xbf# Hello\n\nbody text\n")
    doc = parse_file(p)
    text = doc.pages[0].text
    assert not text.startswith("\ufeff")
    assert text.startswith("# Hello")
    # The heading is detected (the QA bug made it a level-0 "\ufeff# Hello").
    assert [(s.title, s.level) for s in section(doc).sections] == [("Hello", 1)]


def test_utf8_bom_stripped_for_txt(tmp_path: Path):
    p = tmp_path / "bom.txt"
    p.write_bytes(b"\xef\xbb\xbfplain body")
    doc = parse_file(p)
    assert doc.pages[0].text == "plain body"


# ----------------------------------------------------------------- M10 ---


def test_latin1_falls_back_to_windows1252_with_warning(tmp_path: Path, caplog):
    p = tmp_path / "latin1.txt"
    # cp1252 bytes that are NOT valid UTF-8 (smart quotes, accented vowels).
    p.write_bytes("Caf\u00e9 na\u00efve \u201csmart\u201d quotes".encode("cp1252"))
    with caplog.at_level(logging.WARNING, logger="okfsmith.parsers.text"):
        doc = parse_file(p)
    text = doc.pages[0].text
    assert "Caf\u00e9 na\u00efve \u201csmart\u201d quotes" in text
    assert "\ufffd" not in text  # never silent replacement characters
    assert any("windows-1252" in r.getMessage() for r in caplog.records), (
        "expected a logged windows-1252 fallback warning"
    )


def test_valid_utf8_does_not_warn(tmp_path: Path, caplog):
    p = tmp_path / "ok.txt"
    p.write_text("Caf\u00e9 \u2014 plain utf-8 \u2014\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="okfsmith.parsers.text"):
        doc = parse_file(p)
    assert doc.pages[0].text.startswith("Caf\u00e9")
    assert not [r for r in caplog.records if "windows-1252" in r.getMessage()]


# ----------------------------------------------------------------- M11 ---


def test_binary_nul_bytes_raise(tmp_path: Path):
    p = tmp_path / "binary.txt"
    p.write_bytes(bytes(range(256)) * 12)  # NULs, but not UTF-16-shaped
    with pytest.raises(BinaryContentError):
        parse_text_file(p)


def test_binary_control_ratio_raises(tmp_path: Path):
    p = tmp_path / "ctrl.md"
    # Valid UTF-8, no NULs, but dominated by control characters.
    p.write_bytes(bytes([0x07, 0x08, 0x0B, 0x0C, 0x1B] * 200))
    with pytest.raises(BinaryContentError):
        parse_text_file(p)


def test_binary_maps_to_clean_skip_via_parse_file(tmp_path: Path):
    p = tmp_path / "binary.md"
    p.write_bytes(b"\x00" + bytes(range(1, 256)) * 12)  # guaranteed NUL byte
    doc = parse_file(p)  # must not raise
    assert doc.pages == []
    assert "error" in doc.meta
    assert "BinaryContentError" in doc.meta["error"]
    assert "binary" in doc.meta["error"].lower()


def test_binary_error_is_catchable_value_error(tmp_path: Path):
    p = tmp_path / "b2.txt"
    p.write_bytes(b"\x00\x01\x02binary")
    with pytest.raises(ValueError):
        parse_text_file(p)


def test_normal_text_with_tabs_and_newlines_passes(tmp_path: Path):
    p = tmp_path / "ok.txt"
    p.write_text("# Title\n\nbody\twith\ttabs\nand newlines\n")
    doc = parse_file(p)
    assert not doc.meta.get("error"), doc.meta
    assert "body\twith\ttabs" in doc.pages[0].text


# ------------------------------------------------------------------ M3 ---


def test_frontmatter_stripped_not_a_section(tmp_path: Path):
    p = tmp_path / "fm.md"
    p.write_text(
        "---\ntitle: My Real Doc\nauthor: Jane\n---\n\n# Actual Section\n\nbody\n"
        + "x " * 400
    )
    doc = parse_file(p)
    secs = section(doc).sections
    titles = [s.title for s in secs]
    assert "---" not in titles
    assert titles[0] == "Actual Section"
    assert not any("author: Jane" in s.text for s in secs)
    assert not any("title: My Real Doc" in s.text for s in secs)


def test_frontmatter_closing_dots_stripped(tmp_path: Path):
    p = tmp_path / "fm2.md"
    p.write_text("---\ntitle: T\n...\n\n# H\n\nbody\n" + "x " * 400)
    secs = section(parse_file(p)).sections
    assert [s.title for s in secs] == ["H"]


def test_non_mapping_frontmatter_kept(tmp_path: Path):
    # A fenced block that is not a YAML mapping is content, not frontmatter;
    # it must not be silently dropped.
    p = tmp_path / "fm3.md"
    p.write_text("---\n- a\n- b\n---\n\n# H\n\nbody\n" + "x " * 400)
    doc = parse_file(p)
    assert "- a\n- b" in doc.pages[0].text


def test_unclosed_fence_kept(tmp_path: Path):
    p = tmp_path / "fm4.md"
    p.write_text("---\ntitle: T\n\nno closing fence\n")
    doc = parse_file(p)
    assert doc.pages[0].text.startswith("---\ntitle: T")


def test_horizontal_rule_without_mapping_kept(tmp_path: Path):
    p = tmp_path / "hr.md"
    p.write_text("---\nsome intro text\n---\n\n# H\n\nbody\n" + "x " * 400)
    doc = parse_file(p)
    assert "some intro text" in doc.pages[0].text


def test_frontmatter_not_stripped_from_txt(tmp_path: Path):
    # M3 is scoped to markdown sources; .txt keeps its content verbatim.
    p = tmp_path / "notes.txt"
    p.write_text("---\ntitle: T\n---\n\nbody\n")
    doc = parse_file(p)
    assert doc.pages[0].text.startswith("---\ntitle: T")


def test_frontmatter_stripped_for_markdown_suffix(tmp_path: Path):
    p = tmp_path / "fm.markdown"
    p.write_text("---\ntitle: T\n---\n\n# H\n\nbody\n" + "x " * 400)
    secs = section(parse_file(p)).sections
    assert [s.title for s in secs] == ["H"]
