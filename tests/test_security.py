"""Regression tests for the security-audit-3 code findings.

Each test pins one fix so a future refactor cannot silently reopen the hole:
link-target containment, ZipSlip/zip-bomb guards, symlink skipping in
``Bundle.load``, mermaid label escaping, subdir traversal rejection,
path-free human-review errors, and tag normalization in the pipeline.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from okfsmith.core.bundle import Bundle
from okfsmith.core.indexlog import _norm_subdir
from okfsmith.extract.human_review import mark_reviewed
from okfsmith.extract.pipeline import _tag_list
from okfsmith.links import mermaid_flowchart, resolve_link
from okfsmith.parsers.ziputil import safe_extract

FIXTURES = Path(__file__).resolve().parents[1] / ".contract" / "fixtures"


# ---------------------------------------------------------------------------
# Link resolution containment (audit-3 finding 1)
# ---------------------------------------------------------------------------


def test_resolve_link_escaping_bundle_is_dead_not_crash(tmp_path):
    root = tmp_path / "bundle"
    root.mkdir()
    planted = tmp_path / "planted.md"
    planted.write_text("secret", encoding="utf-8")  # exists on the host
    source = root / "a.md"
    source.write_text("x", encoding="utf-8")
    # A link trying to climb out of the bundle must become a dead link —
    # never resolve to (or probe) the host file.
    kind, target = resolve_link(root, source, "../../planted.md")
    assert kind == "dead"
    assert target is None


def test_resolve_link_inside_bundle_still_works(tmp_path):
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "b.md").write_text("x", encoding="utf-8")
    source = root / "a.md"
    source.write_text("x", encoding="utf-8")
    kind, target = resolve_link(root, source, "b.md")
    assert kind == "ok"
    assert target == "b"


# ---------------------------------------------------------------------------
# Zip guards (audit-3 finding 2)
# ---------------------------------------------------------------------------


def _make_zip(tmp_path: Path, members: dict[str, bytes]) -> Path:
    zpath = tmp_path / "evil.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return zpath


def _extract_guarded(zpath: Path, dest: Path) -> Path:
    with zipfile.ZipFile(zpath, "r") as zf:
        return safe_extract(zf, dest)


def test_safe_extract_rejects_zipslip(tmp_path):
    zpath = _make_zip(tmp_path, {"../evil.txt": b"pwned"})
    with pytest.raises(ValueError, match="unsafe member"):
        _extract_guarded(zpath, tmp_path / "out")
    assert not (tmp_path / "evil.txt").exists()


def test_safe_extract_rejects_member_count_bomb(tmp_path, monkeypatch):
    import okfsmith.parsers.ziputil as zu

    monkeypatch.setattr(zu, "MAX_MEMBERS", 2)
    zpath = _make_zip(tmp_path, {f"f{i}.txt": b"x" for i in range(3)})
    with pytest.raises(ValueError, match="[Mm]ember"):
        _extract_guarded(zpath, tmp_path / "out")


def test_safe_extract_rejects_size_bomb(tmp_path, monkeypatch):
    import okfsmith.parsers.ziputil as zu

    monkeypatch.setattr(zu, "MAX_TOTAL_UNCOMPRESSED", 10)
    zpath = _make_zip(tmp_path, {"big.txt": b"x" * 100})
    with pytest.raises(ValueError, match="[Ss]ize|[Ll]imit"):
        _extract_guarded(zpath, tmp_path / "out")


def test_safe_extract_happy_path(tmp_path):
    zpath = _make_zip(tmp_path, {"a.txt": b"hello", "sub/b.txt": b"world"})
    out = _extract_guarded(zpath, tmp_path / "out")
    assert (out / "a.txt").read_text() == "hello"
    assert (out / "sub" / "b.txt").read_text() == "world"


# ---------------------------------------------------------------------------
# Symlink skipping in Bundle.load (audit-3 finding 3)
# ---------------------------------------------------------------------------


def test_bundle_load_skips_symlinked_concept(tmp_path):
    bundle_dir = tmp_path / "bundle"
    (bundle_dir / "real").mkdir(parents=True)
    (bundle_dir / "real" / "ok.md").write_text(
        "---\ntype: Note\ntitle: Real\n---\nbody\n", encoding="utf-8"
    )
    outside = tmp_path / "outside.md"
    outside.write_text("---\ntype: Note\ntitle: Evil\n---\nbody\n", encoding="utf-8")
    (bundle_dir / "real" / "evil.md").symlink_to(outside)
    bundle = Bundle.load(bundle_dir)
    ids = [c.id for c in bundle.iter_concepts()]
    assert "real/ok" in ids
    assert "real/evil" not in ids


# ---------------------------------------------------------------------------
# Mermaid label escaping (audit-3 finding 4)
# ---------------------------------------------------------------------------


def test_mermaid_escapes_closing_bracket():
    data = {
        "nodes": [{"id": "a", "type": "Note", "title": "Weird ] title"}],
        "edges": [],
    }
    chart = mermaid_flowchart(data)
    # A raw "]" inside a label would close the node shape early; the
    # sanitized output must not contain an unescaped " ] " label break.
    assert "Weird ] title" not in chart


# ---------------------------------------------------------------------------
# Subdir traversal (audit-3 finding 5)
# ---------------------------------------------------------------------------


def test_norm_subdir_rejects_parent_traversal():
    with pytest.raises(ValueError):
        _norm_subdir("..")
    with pytest.raises(ValueError):
        _norm_subdir("a/../../b")


def test_norm_subdir_accepts_plain_names():
    assert _norm_subdir("draft") == "draft"
    assert _norm_subdir("a/b") == "a/b"


# ---------------------------------------------------------------------------
# Human-review error hygiene (audit-3 finding 6)
# ---------------------------------------------------------------------------


def test_mark_reviewed_missing_concept_hides_bundle_path(tmp_path):
    bundle = Bundle.load(FIXTURES / "valid")
    with pytest.raises(KeyError) as excinfo:
        mark_reviewed(bundle, "nope/missing", "reviewer")
    assert str(FIXTURES) not in str(excinfo.value)
    assert "nope/missing" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Tag normalization (audit-3 finding 7)
# ---------------------------------------------------------------------------


def test_tag_list_string_is_not_split_into_characters():
    assert _tag_list("abc") == ["abc"]


def test_tag_list_mixed_types_do_not_crash():
    assert _tag_list(["a", 1, None, "b"]) == ["a", "1", "None", "b"]
    assert _tag_list(None) == []


# ---------------------------------------------------------------------------
# Viz markdown renderer: link scheme restriction (XSS regression)
# ---------------------------------------------------------------------------


def test_viz_markdown_links_restrict_url_schemes(tmp_path):
    """md() must not turn javascript:/data:/vbscript: URLs into clickable anchors.

    Concept descriptions/bodies come from ingested (untrusted) documents and
    are rendered by the md() JS function. Only http/https/mailto, fragments,
    and relative URLs may become <a> elements; anything with another scheme
    must degrade to plain text.
    """
    import re

    from okfsmith.viz import render_html

    out = render_html(FIXTURES / "valid", tmp_path / "viz.html")
    text = out.read_text(encoding="utf-8")

    # The scheme gate exists and allowlists http/https/mailto.
    assert "function safeHref(u)" in text
    assert "https?:" in text and "mailto:" in text
    # A generic scheme detector rejects everything else (javascript:, data:, ...).
    assert re.search(r"\^?\[a-zA-Z\]\[a-zA-Z0-9", text)
    # Protocol-relative URLs are rejected too.
    assert 'indexOf("//")' in text
    # md() routes every markdown-link href through the gate ...
    assert "safeHref(u)" in text
    # ... and the old unguarded replacement is gone.
    assert "'<a href=\"$2\"'" not in text


def test_viz_markdown_links_behavioral_node(tmp_path):
    """Behavioral: run the shipped md() in node; evil schemes (incl. leading
    C0 controls, which browsers strip per WHATWG URL) must not produce anchors.
    """
    import json
    import re
    import shutil
    import subprocess

    from okfsmith.viz import render_html

    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available for behavioral JS test")

    out = render_html(FIXTURES / "valid", tmp_path / "viz.html")
    text = out.read_text(encoding="utf-8")
    esc = re.search(r"function esc\(s\) \{.*?\n\}", text, re.S).group(0)
    safe = re.search(r"function safeHref\(u\) \{.*?\n\}", text, re.S).group(0)
    md = re.search(r"function md\(s\) \{.*?\n\}", text, re.S).group(0)

    evil = [
        "[x](javascript:alert(1))",
        "[x](JaVaScRiPt:alert(1))",
        "[x](data:text/html;base64,PHNjcmlwdD4=)",
        "[x](vbscript:msgbox(1))",
        "[x](//evil.com/x)",
        "[x](\x01javascript:alert(1))",
        "[x](\x0ejavascript:alert(1))",
        "[x](\x07javascript:alert(1))",
    ]
    good = [
        "[x](https://example.com)",
        "[x](http://example.com/a?b=1&c=2)",
        "[x](mailto:a@b.c)",
        "[x](#frag)",
        "[x](rel/path.md)",
    ]
    driver = (
        esc + "\n" + safe + "\n" + md
        + "\nvar cases = "
        + json.dumps([["evil", c] for c in evil] + [["good", c] for c in good])
        + ";\nvar out = cases.map(function(pair){ return pair[0] + ':' + (md(pair[1]).indexOf('<a href=') !== -1 ? 'ANCHOR' : 'TEXT'); });\n"
        + "console.log(JSON.stringify(out));"
    )
    proc = subprocess.run(
        [node, "-e", driver], capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0, proc.stderr
    results = json.loads(proc.stdout)
    for kind, result in (r.split(":", 1) for r in results):
        if kind == "evil":
            assert result == "TEXT", f"evil URL produced an anchor: {result}"
        else:
            assert result == "ANCHOR", f"good URL lost its anchor: {result}"
