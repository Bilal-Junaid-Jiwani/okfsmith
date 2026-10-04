"""Regression tests: section-concept link resolution is shared.

A link written in a per-section concept (id ``doc/section``) is relative to
the source *document*. The dashboard's Explore graph learned this in 0.5.1
(viz ``_build_model``); these tests prove the rule now lives in the shared
``okfsmith.links`` resolver, so ``okfsmith graph`` (``build_graph``) and the
W001 validator agree with it — no more spurious dead links / W001 warnings
for interlinked documents, while genuinely broken and escaping links stay
dead.
"""

from __future__ import annotations

from okfsmith.core.bundle import Bundle
from okfsmith.links import build_graph, primary_section_id, resolve_link
from okfsmith.validate import check


def _bundle(tmp_path, concepts) -> Bundle:
    """Build a bundle on disk; *concepts* maps id -> (frontmatter, body)."""
    bundle = Bundle(tmp_path / "kb")
    for cid, (fm, body) in concepts.items():
        bundle.write_concept(cid, fm, body)
    return bundle


def _w001(report) -> list:
    return [f for f in report.warnings if f.code == "W001"]


def _primary_bundle(tmp_path):
    """Bundle where the beta document's primary section slug matches the stem."""
    return _bundle(
        tmp_path,
        {
            "alpha/alpha-guide": ({"type": "note"}, "see [Beta](beta.md)\n"),
            "beta/beta": ({"type": "note"}, "primary section\n"),
            "beta/beta-appendix": ({"type": "note"}, "extra section\n"),
        },
    )


# ---------------------------------------------------------------------------
# build_graph: the shared fallback
# ---------------------------------------------------------------------------


def test_section_link_targets_primary_section(tmp_path):
    # The reported bug: alpha/alpha-guide links beta.md; the beta document
    # was split into per-section concepts. The edge must target beta's
    # primary section (section slug == file stem), not a dead link.
    bundle = _primary_bundle(tmp_path)
    graph = build_graph(bundle)
    assert {"from": "alpha/alpha-guide", "to": "beta/beta"} in graph["edges"]
    assert graph["dead_links"] == []


def test_genuinely_broken_link_still_dead(tmp_path):
    bundle = _bundle(
        tmp_path,
        {
            "alpha/alpha-guide": ({"type": "note"}, "see [Nope](nope.md)\n"),
            "beta/beta-guide": ({"type": "note"}, "primary\n"),
        },
    )
    graph = build_graph(bundle)
    assert graph["edges"] == []
    assert graph["dead_links"] == [{"source": "alpha/alpha-guide", "target": "nope.md"}]


def test_closer_scope_nested_id_still_wins(tmp_path):
    # A directly resolvable nested id beats the document-level fallback.
    bundle = _bundle(
        tmp_path,
        {
            "guide/related": ({"type": "note"}, "see [other](other.md)\n"),
            "guide/other": ({"type": "note"}, "nested\n"),
            "other/primary": ({"type": "note"}, "doc-level\n"),
        },
    )
    graph = build_graph(bundle)
    assert {"from": "guide/related", "to": "guide/other"} in graph["edges"]
    assert graph["dead_links"] == []


def test_escaping_link_stays_dead_with_concept_ids(tmp_path):
    # Security invariant: a link climbing out of the bundle must stay dead
    # even when a concept with the climbed-to name exists and concept ids
    # are passed (the fallback never runs for escaping targets).
    bundle = _bundle(
        tmp_path,
        {
            "a": ({"type": "note"}, "see [evil](../../evil.md)\n"),
            "evil": ({"type": "note"}, "exists but must not be linked\n"),
        },
    )
    graph = build_graph(bundle)
    assert graph["edges"] == []
    assert graph["dead_links"] == [{"source": "a", "target": "../../evil.md"}]
    root = bundle.root
    kind, _ = resolve_link(
        root, root / "a.md", "../../evil.md", concept_ids={"a", "evil"}
    )
    assert kind == "dead"


def test_resolve_link_without_concept_ids_keeps_old_behavior(tmp_path):
    # Without concept ids the resolver is exactly the old file-path logic.
    root = tmp_path / "kb"
    root.mkdir()
    (root / "beta.md").write_text("x", encoding="utf-8")
    kind, cid = resolve_link(root, root / "alpha.md", "beta.md")
    assert (kind, cid) == ("ok", "beta")
    (root / "beta.md").unlink()
    kind, cid = resolve_link(root, root / "alpha.md", "beta.md")
    assert (kind, cid) == ("dead", None)


# ---------------------------------------------------------------------------
# primary_section_id: selection order
# ---------------------------------------------------------------------------


def test_primary_section_prefers_stem_match():
    ids = {"doc/appendix", "doc/doc"}
    assert primary_section_id(ids, "doc") == "doc/doc"


def test_primary_section_prefers_earliest_generated_then_alpha():
    ids = {"doc/b", "doc/a"}
    gen = {"doc/b": "2026-01-02T00:00:00", "doc/a": "2026-01-01T00:00:00"}
    assert primary_section_id(ids, "doc", lambda i: gen[i]) == "doc/a"
    assert primary_section_id(ids, "doc") == "doc/a"


def test_primary_section_none_when_no_sections():
    assert primary_section_id({"other/x"}, "doc") is None


# ---------------------------------------------------------------------------
# W001 validator agrees with the graph
# ---------------------------------------------------------------------------


def test_w001_no_warning_for_section_link(tmp_path):
    bundle = _primary_bundle(tmp_path)
    report = check(bundle.root)
    assert _w001(report) == []


def test_w001_still_flags_broken_link(tmp_path):
    bundle = _bundle(
        tmp_path,
        {
            "alpha/alpha-guide": ({"type": "note"}, "see [Nope](nope.md)\n"),
            "beta/beta-guide": ({"type": "note"}, "primary\n"),
        },
    )
    report = check(bundle.root)
    findings = _w001(report)
    assert len(findings) == 1
    assert findings[0].file == "alpha/alpha-guide.md"
    assert "nope.md" in findings[0].message


# ---------------------------------------------------------------------------
# The three surfaces agree
# ---------------------------------------------------------------------------


def test_graph_and_viz_agree_on_section_links(tmp_path):
    # CLI graph (links.build_graph) and the dashboard Explore graph
    # (viz._build_model) must produce the same live edges.
    from okfsmith.viz import _build_model

    bundle = _primary_bundle(tmp_path)
    graph = build_graph(bundle)
    model = _build_model(bundle)
    live = {(e["from"], e["to"]) for e in model["edges"] if not e["dead"]}
    assert live == {(e["from"], e["to"]) for e in graph["edges"]}
    assert graph["dead_links"] == []
