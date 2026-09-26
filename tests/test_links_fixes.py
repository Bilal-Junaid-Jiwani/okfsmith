"""Regression tests for links QA fixes: H3, H14, M14, M15, L2, L4, L6, L7, L8, L9.

Covers:
- H3  — ReDoS-hardened link extraction: 40 KB adversarial input completes in
        milliseconds (was ~13-23 s); bodies capped at 1 MiB.
- H14 — null byte in a link target resolves "dead", no ValueError.
- M14 — links to existing non-markdown files resolve "asset", not "dead".
- M15 — collision-free mermaid node ids (``x/y`` vs ``x-y``).
- L2  — dead links appear as comments in mermaid output.
- L4  — link targets with spaces and ``<...>``-wrapped targets are extracted.
- L6  — protocol-relative ``//x`` links resolve "external".
- L7  — over-long targets (OSError from is_file) resolve "dead", no traceback.
- L8  — ``orphans()`` survives a non-UTF-8 nested ``index.md``.
- L9  — links to reserved ``index.md``/``log.md`` resolve "reserved", not dead.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from okfsmith import links as links_mod
from okfsmith.core.bundle import Bundle
from okfsmith.links import (
    _node_id,
    build_graph,
    extract_link_targets,
    mermaid_flowchart,
    orphans,
    resolve_link,
)

_FM = "---\ntitle: T\ndescription: D\n---\n"


def _make_bundle(tmp_path: Path, files: dict) -> Bundle:
    root = tmp_path / "kb"
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    return Bundle.load(root)


def _root_of(bundle: Bundle) -> Path:
    return bundle.root


# ---------------------------------------------------------------------------
# H3 — ReDoS guard
# ---------------------------------------------------------------------------


def test_h3_open_brackets_40k_completes_fast():
    # QA repro shape: "[" * 40000 took ~13-23 s before the fix.
    body = "[" * 40000
    start = time.perf_counter()
    targets = extract_link_targets(body)
    elapsed = time.perf_counter() - start
    assert targets == []
    assert elapsed < 5.0, f"took {elapsed:.2f}s"


def test_h3_repeated_link_openers_complete_fast():
    # "[a](" * 20000 took ~130 s before the fix (target group scanned to EOF
    # from every opener).
    body = "[a](" * 20000
    start = time.perf_counter()
    targets = extract_link_targets(body)
    elapsed = time.perf_counter() - start
    assert targets == []
    assert elapsed < 5.0, f"took {elapsed:.2f}s"


def test_h3_many_legit_links_stay_fast():
    body = "".join(f"[t{i}](target-{i}.md) " for i in range(20000))
    start = time.perf_counter()
    targets = extract_link_targets(body)
    elapsed = time.perf_counter() - start
    assert len(targets) == 20000
    assert elapsed < 5.0, f"took {elapsed:.2f}s"


def test_h3_body_capped_at_1mib():
    body = "x" * 2_000_000
    start = time.perf_counter()
    assert extract_link_targets(body) == []
    assert time.perf_counter() - start < 5.0
    # A link past the cap is not extracted (documented DoS guard).
    assert extract_link_targets("x" * 1_000_000 + "[a](b.md)") == []


def test_h3_extraction_still_correct():
    assert extract_link_targets('[go](b.md "The B page")') == ["b.md"]
    assert extract_link_targets("[b](2.md) [a](1.md) [b](2.md)") == ["2.md", "1.md"]
    assert extract_link_targets("![img](x.png) [a](b.md)") == ["b.md"]
    assert extract_link_targets("[[a](b.md)](c.md)") == ["b.md"]
    assert extract_link_targets(None) == []


# ---------------------------------------------------------------------------
# H14 — null bytes
# ---------------------------------------------------------------------------


def test_h14_null_byte_target_is_dead_not_crash(tmp_path: Path):
    bundle = _make_bundle(tmp_path, {"index.md": "# I\n", "a.md": _FM + "body\n"})
    root = _root_of(bundle)
    assert resolve_link(root, root / "a.md", "a\0b.md") == ("dead", None)


def test_h14_null_byte_in_graph_build(tmp_path: Path):
    bundle = _make_bundle(
        tmp_path,
        {"index.md": "# I\n", "a.md": _FM + "[x](a\0b.md)\n"},
    )
    graph = build_graph(bundle)
    assert graph["dead_links"] == [{"source": "a", "target": "a\0b.md"}]


# ---------------------------------------------------------------------------
# M14 — asset links
# ---------------------------------------------------------------------------


def test_m14_existing_non_markdown_file_is_asset(tmp_path: Path):
    bundle = _make_bundle(
        tmp_path,
        {
            "index.md": "# I\n",
            "a.md": _FM + "[txt](notes.txt)\n",
            "notes.txt": "hello\n",
        },
    )
    root = _root_of(bundle)
    assert resolve_link(root, root / "a.md", "notes.txt") == ("asset", None)


def test_m14_asset_not_a_dead_link(tmp_path: Path):
    bundle = _make_bundle(
        tmp_path,
        {
            "index.md": "# I\n",
            "a.md": _FM + "[txt](notes.txt) [img](pic.png)\n",
            "notes.txt": "hello\n",
            "pic.png": "fakepng",
        },
    )
    graph = build_graph(bundle)
    assert graph["dead_links"] == []
    assert graph["edges"] == []


def test_m14_missing_non_markdown_file_still_dead(tmp_path: Path):
    bundle = _make_bundle(tmp_path, {"index.md": "# I\n", "a.md": _FM + "body\n"})
    root = _root_of(bundle)
    assert resolve_link(root, root / "a.md", "gone.txt") == ("dead", None)


# ---------------------------------------------------------------------------
# M15 — collision-free mermaid node ids
# ---------------------------------------------------------------------------


def test_m15_node_ids_are_injective():
    assert _node_id("x/y") != _node_id("x-y")
    assert _node_id("a b") != _node_id("a_b")
    assert _node_id("x/y") != _node_id("x_u002f_y")  # escape char itself escaped
    assert len({_node_id(c) for c in ["x/y", "x-y", "x.y", "x y", "x_y"]}) == 5


def test_m15_mermaid_has_no_phantom_self_loop():
    graph = {
        "nodes": [
            {"id": "x/y", "type": "", "title": "X Y"},
            {"id": "x-y", "type": "", "title": "X-Y"},
        ],
        "edges": [{"from": "x/y", "to": "x-y"}],
        "dead_links": [],
    }
    chart = mermaid_flowchart(graph)
    node_lines = [ln for ln in chart.splitlines() if '["' in ln]
    assert len(node_lines) == 2  # two distinct node declarations
    edge_lines = [ln for ln in chart.splitlines() if "-->" in ln]
    assert len(edge_lines) == 1
    match = re.search(r"(\S+)\s*-->\s*(\S+)", edge_lines[0])
    assert match is not None
    assert match.group(1) != match.group(2)  # not a self-loop


# ---------------------------------------------------------------------------
# L2 — dead links as mermaid comments
# ---------------------------------------------------------------------------


def test_l2_dead_links_in_mermaid_output_as_comments():
    graph = {
        "nodes": [{"id": "a", "type": "", "title": "A"}],
        "edges": [],
        "dead_links": [
            {"source": "a", "target": "missing.md"},
            {"source": "a", "target": "gone.md#frag"},
        ],
    }
    chart = mermaid_flowchart(graph)
    assert "%% dead link: a -> missing.md" in chart
    assert "%% dead link: a -> gone.md#frag" in chart


def test_l2_mermaid_without_dead_links_key_still_works():
    chart = mermaid_flowchart({"nodes": [], "edges": []})
    assert chart.startswith("flowchart LR")


# ---------------------------------------------------------------------------
# L4 — targets with spaces / angle-wrapped targets
# ---------------------------------------------------------------------------


def test_l4_target_with_spaces_extracted():
    assert extract_link_targets("[sp](my doc.md)") == ["my doc.md"]


def test_l4_angle_wrapped_target_extracted():
    assert extract_link_targets("[sp](<my doc.md>)") == ["my doc.md"]
    assert extract_link_targets('[sp](<my doc.md> "T")') == ["my doc.md"]


def test_l4_spaced_target_resolves_to_concept(tmp_path: Path):
    bundle = _make_bundle(
        tmp_path,
        {
            "index.md": "# I\n",
            "a.md": _FM + "[sp](my doc.md)\n",
            "my doc.md": _FM + "body\n",
        },
    )
    graph = build_graph(bundle)
    assert graph["edges"] == [{"from": "a", "to": "my doc"}]
    assert graph["dead_links"] == []


# ---------------------------------------------------------------------------
# L6 — protocol-relative links are external
# ---------------------------------------------------------------------------


def test_l6_protocol_relative_is_external(tmp_path: Path):
    bundle = _make_bundle(
        tmp_path,
        {
            "index.md": "# I\n",
            "a.md": _FM + "[pr](//other.md)\n",
            "other.md": _FM + "body\n",
        },
    )
    root = _root_of(bundle)
    assert resolve_link(root, root / "a.md", "//other.md") == ("external", None)
    graph = build_graph(bundle)
    assert graph["edges"] == []
    assert graph["dead_links"] == []


# ---------------------------------------------------------------------------
# L7 — OSError from is_file()
# ---------------------------------------------------------------------------


def test_l7_overlong_target_is_dead_not_crash(tmp_path: Path):
    bundle = _make_bundle(tmp_path, {"index.md": "# I\n", "a.md": _FM + "body\n"})
    root = _root_of(bundle)
    assert resolve_link(root, root / "a.md", "x" * 10000 + ".md") == ("dead", None)


# ---------------------------------------------------------------------------
# L8 — orphans() UnicodeDecodeError
# ---------------------------------------------------------------------------


def test_l8_orphans_survives_non_utf8_nested_index(tmp_path: Path):
    bundle = _make_bundle(
        tmp_path,
        {
            "index.md": "# I\n",
            # Invalid UTF-8 nested index: Bundle.load never reads it (reserved),
            # but orphans() walks it.
            "sub/index.md": b"# Sub\n\n[\xff\xfe]\n",
            "sub/thing.md": _FM + "body\n",
        },
    )
    assert orphans(bundle) == ["sub/thing"]


# ---------------------------------------------------------------------------
# L9 — reserved files
# ---------------------------------------------------------------------------


def test_l9_reserved_links_are_not_dead(tmp_path: Path):
    bundle = _make_bundle(
        tmp_path,
        {
            "index.md": "# I\n",
            "log.md": "# L\n",
            "a.md": _FM + "[i](index.md) [l](log.md)\n",
        },
    )
    root = _root_of(bundle)
    assert resolve_link(root, root / "a.md", "index.md") == ("reserved", None)
    assert resolve_link(root, root / "a.md", "log.md") == ("reserved", None)
    graph = build_graph(bundle)
    assert graph["dead_links"] == []
    assert graph["edges"] == []


def test_l9_reserved_case_insensitive(tmp_path: Path):
    bundle = _make_bundle(
        tmp_path,
        {"index.md": "# I\n", "a.md": _FM + "[i](INDEX.MD)\n"},
    )
    root = _root_of(bundle)
    assert resolve_link(root, root / "a.md", "INDEX.MD") == ("reserved", None)


# ---------------------------------------------------------------------------
# Shared-extractor contract (coordination decision)
# ---------------------------------------------------------------------------


def test_shared_extractor_name_and_signature_stable():
    import inspect

    assert links_mod.extract_link_targets.__name__ == "extract_link_targets"
    sig = inspect.signature(links_mod.extract_link_targets)
    assert list(sig.parameters) == ["body"]
