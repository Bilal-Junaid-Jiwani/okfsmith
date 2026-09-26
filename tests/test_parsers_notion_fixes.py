"""Regression tests for QA findings H5 and L19 (Notion parser).

H5:  text-only Notion exports (no ``_files/`` directory) must parse —
     markdown members are treated as pages instead of misrouting to the
     office zip path and being dropped.
L19: ``notion_resource_url`` must not capture trailing sentence punctuation;
     an empty CSV in an export must yield 0 pages and never ``needs_ocr``.
"""

import zipfile
from pathlib import Path

from okfsmith.parsers import notion, parse_file

NOTION_HASH = "a1b2c3d4e5f60718293a4b5c6d7e8f90"  # 32 lowercase hex, like exports


def _make_zip(path: Path, members: dict[str, str | bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


# ------------------------------------------------------------------ H5 ---
def test_text_only_notion_export_is_detected(tmp_path: Path):
    zf = _make_zip(
        tmp_path / "text-only.zip",
        {f"Plain Page {NOTION_HASH}.md": "# Plain Page\n\nJust text.\n"},
    )
    assert notion.looks_like_notion_export(zf) is True


def test_text_only_notion_export_parses(tmp_path: Path):
    zf = _make_zip(
        tmp_path / "text-only.zip",
        {
            f"Plain Page {NOTION_HASH}.md": "# Plain Page\n\nJust text.\n",
            f"Second {NOTION_HASH}.md": "# Second\n\nMore text here.\n",
        },
    )
    doc = parse_file(zf)
    assert doc.meta.get("notion") is True
    assert doc.meta.get("parser") == "notion"
    assert len(doc.pages) == 2
    assert "Just text." in doc.pages[0].text
    titles = [e["title"] for e in doc.meta["notion_pages"]]
    assert titles == ["Plain Page", "Second"]


def test_notion_export_with_assets_still_parses(tmp_path: Path):
    # Back-compat: an export WITH _files/ behaves exactly as before.
    zf = _make_zip(
        tmp_path / "export.zip",
        {
            f"My Page {NOTION_HASH}.md": "# My Page\n\nHi there.\n",
            f"My Page {NOTION_HASH}_files/logo.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 16,
        },
    )
    assert notion.looks_like_notion_export(zf) is True
    doc = parse_file(zf)
    assert doc.meta.get("notion") is True
    assert len(doc.pages) == 1
    entry = doc.meta["notion_pages"][0]
    assert entry["title"] == "My Page"
    assert entry["assets"] == ["logo.png"]


def test_non_notion_zip_not_detected(tmp_path: Path):
    zf = _make_zip(tmp_path / "plain.zip", {"a.txt": "alpha content here"})
    assert notion.looks_like_notion_export(zf) is False


# ----------------------------------------------------------------- L19 ---
def test_notion_url_trailing_punctuation_stripped():
    assert (
        notion.notion_resource_url("see https://www.notion.so/x-abc123, ok")
        == "https://www.notion.so/x-abc123"
    )
    assert (
        notion.notion_resource_url("visit https://www.notion.so/x-abc123. Bye")
        == "https://www.notion.so/x-abc123"
    )
    assert (
        notion.notion_resource_url("(https://notion.so/x-abc123)! done")
        == "https://notion.so/x-abc123"
    )
    assert (
        notion.notion_resource_url("link: https://www.notion.so/x-abc123? ok")
        == "https://www.notion.so/x-abc123"
    )
    # URLs whose real last char is punctuation-adjacent are left intact.
    assert (
        notion.notion_resource_url("https://www.notion.so/x-abc123-1a2b")
        == "https://www.notion.so/x-abc123-1a2b"
    )
    assert notion.notion_resource_url("no links here") is None


def test_empty_csv_yields_no_pages_and_no_needs_ocr(tmp_path: Path):
    zf = _make_zip(
        tmp_path / "empty-csv.zip",
        {
            f"P {NOTION_HASH}.md": "# P\n\nok\n",
            f"D {NOTION_HASH}.csv": "",
            f"P {NOTION_HASH}_files/": "",
        },
    )
    docs = notion.parse_notion_export(zf)
    assert [d.meta["notion_title"] for d in docs] == ["P"]

    doc = parse_file(zf)
    assert len(doc.pages) == 1
    assert all(not pg.needs_ocr for pg in doc.pages)


def test_nonempty_csv_page_never_needs_ocr(tmp_path: Path):
    zf = _make_zip(
        tmp_path / "csv.zip",
        {f"Tasks {NOTION_HASH}.csv": "Task,Owner\nWrite tests,Alice\n"},
    )
    doc = parse_file(zf)
    assert len(doc.pages) == 1
    assert doc.pages[0].needs_ocr is False
    assert doc.pages[0].tables[0][0] == ["Task", "Owner"]
