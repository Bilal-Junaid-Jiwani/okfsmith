"""0.8.5 — fixes from the external hands-on review of the offline path.

An independent tester installed okfsmith and ran the ``--no-llm`` pipeline
in a sandbox; six findings came back. Each test below pins one fix:

1. concepts stamped ``generated.by: okfsmith/0.2.0`` (stale hardcoded literal)
2. the 1000-char stub threshold had no user override
3. offline concepts had no ``sources[]`` (docs claimed every concept has one)
4. PDFs became one concept; wrapped lines stayed broken mid-sentence
5. every offline concept shared one generic description
6. the offline graph had 0 links
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from okfsmith import __version__
from okfsmith.cli.app import app
from okfsmith.core import Bundle
from okfsmith.links import build_graph
from okfsmith.parsers import Page, ParsedDocument, parse_file, sectioning
from okfsmith.parsers.ingest_no_llm import DESCRIPTION, GENERATED_BY, ingest_no_llm
from okfsmith.validate import check

runner = CliRunner()

PAD = "Additional supporting detail for this section follows here. " * 40


def _doc(text: str, source: str = "notes.md") -> ParsedDocument:
    return ParsedDocument(
        pages=[Page(number=1, text=text, tables=[])],
        meta={"source": source},
    )


# ------------------------------------------------------------- fix 1 -----


def test_generated_by_uses_installed_version():
    assert GENERATED_BY == f"okfsmith/{__version__}"
    assert GENERATED_BY != "okfsmith/0.2.0"


def test_ingested_concept_stamped_with_real_version(tmp_path: Path):
    bundle = Bundle(tmp_path / "bundle")
    ids = ingest_no_llm(bundle, _doc(f"# Alpha\n\n{PAD}"), "notes.md")
    assert len(ids) == 1
    fm = bundle.get(ids[0]).frontmatter
    assert fm["generated"]["by"] == f"okfsmith/{__version__}"


# ------------------------------------------------------------- fix 2 -----


def test_sectioning_min_chars_override():
    doc = _doc("# Tiny\n\nshort but real")
    assert sectioning.section(doc).too_small is True  # default 1000
    assert sectioning.section(doc, min_chars=10).too_small is False
    assert sectioning.section(doc, min_chars=0).too_small is False


def test_ingest_no_llm_min_chars_creates_concepts(tmp_path: Path):
    bundle = Bundle(tmp_path / "bundle")
    doc = _doc("# Tiny\n\nshort but real")
    assert ingest_no_llm(bundle, doc, "tiny.md") == []
    ids = ingest_no_llm(bundle, doc, "tiny.md", min_chars=10)
    assert len(ids) == 1


def _write_short_note(tmp_path: Path) -> Path:
    src = tmp_path / "note.md"
    src.write_text("# Note\n\nShort but real content here.\n", encoding="utf-8")
    return src


def test_cli_min_chars_ingests_short_file(tmp_path: Path):
    bundle_dir = tmp_path / "kb"
    src = _write_short_note(tmp_path)
    result = runner.invoke(app, ["ingest", str(bundle_dir), str(src), "--no-llm"])
    assert result.exit_code == 0, result.output
    assert list(Bundle.load(bundle_dir).iter_concepts()) == []  # default: skipped

    result = runner.invoke(
        app, ["ingest", str(bundle_dir), str(src), "--no-llm", "--min-chars", "10"]
    )
    assert result.exit_code == 0, result.output
    assert len(list(Bundle.load(bundle_dir).iter_concepts())) == 1


def test_cli_min_chars_dry_run_parity(tmp_path: Path):
    bundle_dir = tmp_path / "kb"
    src = _write_short_note(tmp_path)
    result = runner.invoke(
        app, ["ingest", str(bundle_dir), str(src), "--no-llm", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert "would skip (below 1000-char minimum" in result.output

    result = runner.invoke(
        app,
        ["ingest", str(bundle_dir), str(src), "--no-llm", "--dry-run",
         "--min-chars", "10"],
    )
    assert result.exit_code == 0, result.output
    assert "would skip" not in result.output
    assert "draft concepts" in result.output


def test_cli_min_chars_requires_no_llm(tmp_path: Path):
    src = _write_short_note(tmp_path)
    result = runner.invoke(
        app, ["ingest", str(tmp_path / "kb"), str(src), "--min-chars", "10"]
    )
    assert result.exit_code != 0
    assert "--min-chars only applies with --no-llm" in result.output


def test_cli_min_chars_negative_rejected(tmp_path: Path):
    src = _write_short_note(tmp_path)
    result = runner.invoke(
        app,
        ["ingest", str(tmp_path / "kb"), str(src), "--no-llm",
         "--min-chars", "-1"],
    )
    assert result.exit_code != 0


def test_cli_sync_min_chars(tmp_path: Path):
    bundle_dir = tmp_path / "kb"
    src_dir = tmp_path / "srcs"
    src_dir.mkdir()
    (src_dir / "note.md").write_text(
        "# Note\n\nShort but real content here.\n", encoding="utf-8"
    )
    result = runner.invoke(app, ["sync", str(bundle_dir), str(src_dir), "--no-llm"])
    assert result.exit_code == 0, result.output
    assert list(Bundle.load(bundle_dir).iter_concepts()) == []

    result = runner.invoke(
        app,
        ["sync", str(bundle_dir), str(src_dir), "--no-llm", "--min-chars", "10"],
    )
    assert result.exit_code == 0, result.output
    assert len(list(Bundle.load(bundle_dir).iter_concepts())) == 1


# ------------------------------------------------------------- fix 3 -----


def test_offline_concept_has_sources_and_digest(tmp_path: Path):
    bundle = Bundle(tmp_path / "bundle")
    digest = "a" * 64
    ids = ingest_no_llm(bundle, _doc(f"# Alpha\n\n{PAD}"), "notes.md", digest=digest)
    fm = bundle.get(ids[0]).frontmatter
    assert fm["sources"] == [
        {"id": "source-1", "resource": "notes.md#page=1", "title": "notes.md"}
    ]
    assert fm["source_digest"] == digest


def test_offline_sources_without_digest(tmp_path: Path):
    bundle = Bundle(tmp_path / "bundle")
    ids = ingest_no_llm(bundle, _doc(f"# Alpha\n\n{PAD}"), "notes.md")
    fm = bundle.get(ids[0]).frontmatter
    assert fm["sources"][0]["id"] == "source-1"
    assert fm["sources"][0]["resource"] == "notes.md#page=1"
    assert "source_digest" not in fm


def test_offline_bundle_validates_without_source_warnings(tmp_path: Path):
    bundle = Bundle(tmp_path / "bundle")
    text = f"# Alpha\n\n{PAD}\n\n## Beta\n\n{PAD}\n"
    ids = ingest_no_llm(bundle, _doc(text), "notes.md", digest="b" * 64)
    assert len(ids) == 2
    report = check(bundle.root)
    codes = {f.code for f in report.errors} | {f.code for f in report.warnings}
    # W005/W008/W015 = sources[] shape problems; W001 = dead body links.
    assert not ({"W001", "W005", "W008", "W015"} & codes)


# ------------------------------------------------------------- fix 5 -----


def test_descriptions_derived_per_section(tmp_path: Path):
    bundle = Bundle(tmp_path / "bundle")
    text = (
        "# Refunds\n\nRefunds are issued within thirty days of purchase. "
        + PAD
        + "\n\n# Eligibility\n\nEligibility depends on the product condition. "
        + PAD
    )
    ids = ingest_no_llm(bundle, _doc(text), "policy.md")
    assert len(ids) == 2
    d1 = bundle.get(ids[0]).frontmatter["description"]
    d2 = bundle.get(ids[1]).frontmatter["description"]
    assert d1 == "Refunds are issued within thirty days of purchase."
    assert d2 == "Eligibility depends on the product condition."
    assert d1 != d2
    assert d1 != DESCRIPTION and d2 != DESCRIPTION


def test_description_falls_back_for_tables_only_section(tmp_path: Path):
    bundle = Bundle(tmp_path / "bundle")
    # Tables attach to the first section touching their page, so the
    # tables-only section needs its own page.
    parsed = ParsedDocument(
        pages=[
            Page(number=1, text=f"# Data\n\n{PAD}\n", tables=[]),
            Page(
                number=2,
                text="# Grid\n",
                tables=[[["a", "b"], ["1", "2"]]],
            ),
        ],
        meta={"source": "data.md"},
    )
    ids = ingest_no_llm(bundle, parsed, "data.md")
    assert len(ids) == 2
    grid = next(c for c in map(bundle.get, ids) if c.frontmatter["title"] == "Grid")
    assert grid.frontmatter["description"] == DESCRIPTION


# ------------------------------------------------------------- fix 6 -----


def test_offline_graph_has_sequence_edges(tmp_path: Path):
    bundle = Bundle(tmp_path / "bundle")
    text = f"# One\n\n{PAD}\n\n# Two\n\n{PAD}\n\n# Three\n\n{PAD}\n"
    ids = ingest_no_llm(bundle, _doc(text), "guide.md")
    assert len(ids) == 3
    graph = build_graph(bundle)
    edges = {(e["from"], e["to"]) for e in graph["edges"]}
    assert len(edges) >= 2  # at least the sequence chain
    assert graph["dead_links"] == []
    body = bundle.get(ids[0]).body
    assert "## See also" in body
    assert "next section of guide.md" in body


def test_offline_mention_link(tmp_path: Path):
    bundle = Bundle(tmp_path / "bundle")
    text = (
        "# Overview\n\nThis overview explains the Beta Guide in depth. "
        + PAD
        + "\n\n# Beta Guide\n\nBeta body text. "
        + PAD
    )
    ids = ingest_no_llm(bundle, _doc(text), "guide.md")
    by_title = {bundle.get(i).frontmatter["title"]: i for i in ids}
    graph = build_graph(bundle)
    edges = {(e["from"], e["to"]) for e in graph["edges"]}
    assert (by_title["Overview"], by_title["Beta Guide"]) in edges
    body = bundle.get(by_title["Overview"]).body
    assert "titled section mentioned in this section" in body


def test_offline_single_section_has_no_see_also(tmp_path: Path):
    bundle = Bundle(tmp_path / "bundle")
    ids = ingest_no_llm(bundle, _doc(f"# Solo\n\n{PAD}"), "solo.md")
    assert "## See also" not in bundle.get(ids[0]).body


# ------------------------------------------------------------- fix 4 -----


def _esc(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _write_styled_pdf(path: Path, pages: list[list[tuple[str, int, int, str]]]) -> Path:
    """Minimal PDF; each page is a list of (font, size, y, text) lines.

    Fonts: /F1 Helvetica, /F2 Helvetica-Bold (mirrors tests/_helpers.write_pdf
    but with a second font so heading structure exists).
    """
    objs: list[tuple[int, str]] = []
    kids = " ".join(f"{5 + i} 0 R" for i in range(len(pages)))
    objs.append((1, "<< /Type /Catalog /Pages 2 0 R >>"))
    objs.append((2, f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>"))
    objs.append((3, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"))
    objs.append((4, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"))
    for i in range(len(pages)):
        objs.append(
            (
                5 + i,
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                "/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
                f"/Contents {5 + len(pages) + i} 0 R >>",
            )
        )
    for i, lines in enumerate(pages):
        stream = "\n".join(
            f"BT /{font} {size} Tf 72 {y} Td ({_esc(text)}) Tj ET"
            for font, size, y, text in lines
        )
        objs.append(
            (5 + len(pages) + i, f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
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


def _refund_pdf(path: Path) -> Path:
    body1 = [
        "This document explains the refund policy for all",
        "customers and describes how requests are handled by",
        "the support team within thirty days of purchase.",
    ]
    body2 = [
        "A customer is eligible for a refund when the product",
        "is returned in its original condition with a receipt.",
    ]
    body3 = [
        "To start the process, contact support with your order",
        "number and a brief description of the problem found.",
    ]
    lines: list[tuple[str, int, int, str]] = [("F2", 20, 720, "Introduction")]
    y = 690
    for ln in body1 * 3:
        lines.append(("F1", 11, y, ln))
        y -= 14
    lines.append(("F2", 16, y - 28, "Eligibility"))
    y -= 56
    for ln in body2 * 3:
        lines.append(("F1", 11, y, ln))
        y -= 14
    lines.append(("F2", 16, y - 28, "Process"))
    y -= 56
    for ln in body3 * 3:
        lines.append(("F1", 11, y, ln))
        y -= 14
    return _write_styled_pdf(path, [lines])


def test_pdf_sections_split_by_font_headings(tmp_path: Path):
    pdf = _refund_pdf(tmp_path / "refund.pdf")
    doc = parse_file(pdf)
    text = doc.pages[0].text
    assert "# Introduction" in text
    assert "## Eligibility" in text
    assert "## Process" in text
    result = sectioning.section(doc)
    assert [s.title for s in result.sections] == [
        "Introduction",
        "Eligibility",
        "Process",
    ]
    assert [s.level for s in result.sections] == [1, 2, 2]


def test_pdf_wrapped_lines_joined(tmp_path: Path):
    pdf = _refund_pdf(tmp_path / "refund.pdf")
    doc = parse_file(pdf)
    text = doc.pages[0].text
    # The sentence was hard-wrapped across three extracted lines; the
    # parsed text must carry it as one joined line.
    assert (
        "This document explains the refund policy for all customers and "
        "describes how requests are handled by the support team within "
        "thirty days of purchase." in text
    )


def test_pdf_bold_only_headings_split(tmp_path: Path):
    lines: list[tuple[str, int, int, str]] = [("F2", 11, 720, "First Part")]
    y = 690
    for ln in ["Body text of the first part goes here now."] * 8:
        lines.append(("F1", 11, y, ln))
        y -= 14
    lines.append(("F2", 11, y - 28, "Second Part"))
    y -= 56
    for ln in ["Body text of the second part goes here now."] * 8:
        lines.append(("F1", 11, y, ln))
        y -= 14
    pdf = _write_styled_pdf(tmp_path / "bold.pdf", [lines])
    doc = parse_file(pdf)
    result = sectioning.section(doc)
    assert [s.title for s in result.sections] == ["First Part", "Second Part"]


def test_pdf_end_to_end_concepts_per_section(tmp_path: Path):
    pdf = _refund_pdf(tmp_path / "refund.pdf")
    bundle = Bundle(tmp_path / "bundle")
    parsed = parse_file(pdf)
    ids = ingest_no_llm(bundle, parsed, "refund.pdf")
    titles = {bundle.get(i).frontmatter["title"] for i in ids}
    assert titles == {"Introduction", "Eligibility", "Process"}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
