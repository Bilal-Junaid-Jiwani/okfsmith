"""Tests for okfsmith.viz: self-contained interactive HTML graph rendering.

Proves: render_html writes valid self-contained HTML containing node ids,
trust-tier labels, and dead-link marking; output works offline (no external
script/link tags); empty bundles get a friendly message; unicode titles
survive; 500+ nodes render without crashing.
"""

import re
from pathlib import Path

from okfsmith.core.bundle import Bundle
from okfsmith.viz import render_html

WORKTREE = Path(__file__).resolve().parents[1]
FIXTURES = WORKTREE / ".contract" / "fixtures"
# The cs-curriculum example bundle ships in this repo checkout, so the
# tests use the worktree-relative path (hermetic — no machine-specific
# HOME layout assumed, unlike the old Path.home() hardcode that broke CI).
CS_BUNDLE = WORKTREE / "examples" / "bundles" / "cs-curriculum"


def _script_link_tags(html_text: str) -> list[str]:
    """Return <script src=...> / <link href=...> tags pointing at http(s) URLs."""
    tags = re.findall(r"<script\b[^>]*>", html_text, re.IGNORECASE)
    tags += re.findall(r"<link\b[^>]*>", html_text, re.IGNORECASE)
    return [
        t
        for t in tags
        if re.search(r"""(?:src|href)\s*=\s*["']https?://""", t, re.IGNORECASE)
    ]


def test_render_valid_fixture(tmp_path):
    out = render_html(FIXTURES / "valid", tmp_path / "viz.html")
    assert out == tmp_path / "viz.html"
    assert out.is_file()

    text = out.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in text
    assert "<html" in text and "</html>" in text
    # node ids embedded in the data payload
    for concept_id in ("finance/revenue", "finance/profit", "incidents/playbook"):
        assert concept_id in text
    # trust-tier labels (legend + data + detail panel)
    for tier in ("human-reviewed", "machine-confirmed", "unverified"):
        assert tier in text
    # feature chrome present
    assert 'id="search"' in text
    assert 'id="orphans"' in text
    assert 'id="detail"' in text
    assert "<canvas" in text


def test_render_cs_curriculum_bundle(tmp_path):
    out = render_html(CS_BUNDLE, tmp_path / "viz.html")
    text = out.read_text(encoding="utf-8")
    for concept_id in ("courses/cs101", "topics/recursion", "instructors/grace-hopper"):
        assert concept_id in text
    # md-suffixed body links resolve to live edges (no dead-link ghosts here)
    assert '"dead":true' not in text


def test_dead_links_marked(tmp_path):
    out = render_html(FIXTURES / "warn-dead-link", tmp_path / "viz.html")
    text = out.read_text(encoding="utf-8")
    # the dead target id is present and flagged in the edge payload
    assert "finance/does-not-exist" in text
    assert '"dead":true' in text
    # the legend explains the red-dashed dead-link marking
    assert "dead link" in text


def test_output_is_offline(tmp_path):
    for bundle in (FIXTURES / "valid", CS_BUNDLE):
        text = render_html(bundle, tmp_path / "viz.html").read_text(encoding="utf-8")
        assert _script_link_tags(text) == [], f"external resource tag in {bundle}"
    # sanity: bodies legitimately contain https URLs as *text*, which is fine
    text = (tmp_path / "viz.html").read_text(encoding="utf-8")
    assert "https://" in text  # proves the check above is tag-scoped, not naive


def test_empty_bundle_friendly_message(tmp_path):
    empty = tmp_path / "empty-bundle"
    empty.mkdir()
    text = render_html(empty, tmp_path / "viz.html").read_text(encoding="utf-8")
    assert "Nothing to visualize yet" in text
    assert "no concepts" in text


def test_unicode_titles(tmp_path):
    bundle = Bundle(tmp_path / "unicode")
    bundle.write_concept(
        "notes/uni",
        {"type": "note", "title": "日本語タイトル 🚀 مرحبا", "tags": ["ünïcodé"]},
        "body with unicode: café naïve\n",
    )
    text = render_html(bundle.root, tmp_path / "viz.html").read_text(encoding="utf-8")
    assert "日本語タイトル 🚀 مرحبا" in text
    assert "ünïcodé" in text


def test_accepts_str_paths_and_returns_path(tmp_path):
    bundle = Bundle(tmp_path / "b")
    bundle.write_concept("a", {"type": "note", "title": "A"}, "see [b](/b)\n")
    bundle.write_concept("b", {"type": "note", "title": "B"}, "back to [a](/a)\n")
    out = render_html(str(bundle.root), str(tmp_path / "sub" / "viz.html"))
    assert isinstance(out, Path)
    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    assert '"from":"a","to":"b","dead":false' in text


def test_link_resolution_variants(tmp_path):
    bundle = Bundle(tmp_path / "links")
    bundle.write_concept("docs/a", {"type": "note"}, "up [b](../b) self [me](/docs/a)\n")
    bundle.write_concept("b", {"type": "note"}, "ext [x](https://example.com/y) frag [f](#top)\n")
    text = render_html(bundle.root, tmp_path / "viz.html").read_text(encoding="utf-8")
    # relative ../b resolves to live edge; self-link dropped; external/fragment dropped.
    # (the https URL still appears in the embedded body *text*, which is correct)
    assert '"from":"docs/a","to":"b","dead":false' in text
    assert '"to":"docs/a"' not in text
    assert '"to":"https://example.com/y"' not in text
    assert '"to":"#top"' not in text


def test_500_nodes_renders_without_crashing(tmp_path):
    bundle = Bundle(tmp_path / "big")
    n = 500
    for i in range(n):
        nxt = f"node-{(i + 1) % n}"
        bundle.write_concept(
            f"node-{i}",
            {"type": "note", "title": f"Node {i}"},
            f"links to [{nxt}](/{nxt}) and [missing](/missing-{i})\n",
        )
    out = render_html(bundle.root, tmp_path / "viz.html")
    text = out.read_text(encoding="utf-8")
    assert out.stat().st_size > 100_000
    for i in (0, 123, 499):
        assert f"node-{i}" in text
    # 500 live edges + 500 dead edges
    assert text.count('"dead":false') == n
    assert text.count('"dead":true') == n


# ---------------------------------------------------------------------------
# Panel-D regression tests (UX review fixes, round 1)
# ---------------------------------------------------------------------------


def test_empty_overlay_hidden_rule_present(tmp_path):
    """The #empty flex overlay must not override [hidden] (ship-blocker)."""
    out = render_html(FIXTURES / "valid", tmp_path / "viz.html")
    text = out.read_text(encoding="utf-8")
    assert "#empty[hidden]" in text
    assert re.search(r"#empty\[hidden\]\s*\{\s*display:\s*none", text)


def test_legend_declares_two_honest_channels(tmp_path):
    out = render_html(FIXTURES / "valid", tmp_path / "viz.html")
    text = out.read_text(encoding="utf-8")
    assert "Trust is shown by <b>shape</b>" in text
    assert "concept type by <b>color</b>" in text


def test_canvas_keyboard_accessible(tmp_path):
    out = render_html(FIXTURES / "valid", tmp_path / "viz.html")
    text = out.read_text(encoding="utf-8")
    assert 'tabindex="0"' in text
    assert 'role="img"' in text
    assert "aria-label=" in text
    assert '"Escape"' in text  # Esc closes the detail panel
    assert "focus-visible" in text


def test_screen_reader_concept_list_present(tmp_path):
    out = render_html(FIXTURES / "valid", tmp_path / "viz.html")
    text = out.read_text(encoding="utf-8")
    assert 'id="sr-list"' in text
    assert "sr-only" in text


def test_detail_panel_shows_connections(tmp_path):
    out = render_html(FIXTURES / "valid", tmp_path / "viz.html")
    text = out.read_text(encoding="utf-8")
    assert "linked from" in text
    assert "links to" in text
    assert "backlinks" in text


def test_reset_view_and_match_count_present(tmp_path):
    out = render_html(FIXTURES / "valid", tmp_path / "viz.html")
    text = out.read_text(encoding="utf-8")
    assert 'id="reset-view"' in text
    assert 'id="matchcount"' in text


def test_loading_and_error_states_present(tmp_path):
    out = render_html(FIXTURES / "valid", tmp_path / "viz.html")
    text = out.read_text(encoding="utf-8")
    assert 'id="loading"' in text
    assert 'id="error"' in text
    assert "Laying out the graph" in text


def test_colorblind_safe_palette_used(tmp_path):
    out = render_html(FIXTURES / "valid", tmp_path / "viz.html")
    text = out.read_text(encoding="utf-8")
    # Okabe–Ito palette markers; the old hue-hash coloring is gone.
    assert "#E69F00" in text
    assert "hueFor" not in text


def test_section_concept_links_resolve_to_target_document(tmp_path):
    # Regression: a link written in a per-section concept (id "doc/section")
    # is relative to the source *document*. "guide/related" linking
    # "other.md" must resolve to the primary concept of document "other",
    # not to a dead "guide/other" edge.
    bundle = Bundle(tmp_path / "links")
    bundle.write_concept(
        "guide/related", {"type": "note"}, "see [other](other.md)\n"
    )
    bundle.write_concept(
        "other/other", {"type": "note"}, "primary section\n"
    )
    bundle.write_concept(
        "other/appendix", {"type": "note"}, "extra section\n"
    )
    text = render_html(bundle.root, tmp_path / "viz.html").read_text(encoding="utf-8")
    assert '"from":"guide/related","to":"other/other","dead":false' in text
    assert '"dead":true' not in text


def test_section_concept_link_prefers_closest_scope(tmp_path):
    # When a nested id exists ("docs/other"), it still wins over the
    # document-level fallback.
    bundle = Bundle(tmp_path / "links")
    bundle.write_concept(
        "docs/guide", {"type": "note"}, "see [other](other.md)\n"
    )
    bundle.write_concept("docs/other", {"type": "note"}, "nested doc\n")
    bundle.write_concept("other/other", {"type": "note"}, "top-level doc\n")
    text = render_html(bundle.root, tmp_path / "viz.html").read_text(encoding="utf-8")
    assert '"from":"docs/guide","to":"docs/other","dead":false' in text
