"""Graph carries temporal status (0.26.0).

``search`` / ``list`` / ``read`` already surface whether a concept is
current, superseded, expired, or not yet valid; the graph did not — a
superseded concept rendered as a live node in ``graph --format json``,
``--format text`` and ``--format mermaid`` alike. These tests pin the fix:

- ``build_graph`` nodes carry ``temporal_status`` + ``superseded_by``.
- ``graph --format text`` lists non-current concepts (and only then: a
  plain bundle prints byte-identical output to before).
- ``mermaid_flowchart`` marks non-current node labels, current ones
  byte-identical.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from okfsmith.cli.app import app
from okfsmith.core.bundle import Bundle
from okfsmith.links import build_graph, mermaid_flowchart, temporal_mark

runner = CliRunner()

_OLD = """---
title: Old Policy
type: Note
---
# Old

See [New](new.md).
"""

_NEW = """---
title: New Policy
type: Note
supersedes: old
---
# New

Body.
"""

_EXPIRED = """---
title: Old Offer
type: Note
valid_until: 2020-01-01
---
# Old Offer

Body.
"""

_FUTURE = """---
title: Future Plan
type: Note
valid_from: 2999-01-01
---
# Future Plan

Body.
"""


_PLAIN = """---
title: Plain Note
type: Note
---
# Plain

Body.
"""


def _make_bundle(tmp_path: Path, files: dict) -> Bundle:
    root = tmp_path / "kb"
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return Bundle.load(root)


def _node(graph: dict, concept_id: str) -> dict:
    return next(n for n in graph["nodes"] if n["id"] == concept_id)


# ---------------------------------------------------------------------------
# build_graph nodes
# ---------------------------------------------------------------------------


def test_superseded_node_carries_status_and_head(tmp_path: Path):
    bundle = _make_bundle(
        tmp_path, {"index.md": "# I\n", "old.md": _OLD, "new.md": _NEW}
    )
    graph = build_graph(bundle)
    old = _node(graph, "old")
    assert old["temporal_status"] == "superseded"
    assert old["superseded_by"] == "new"
    new = _node(graph, "new")
    assert new["temporal_status"] == "current"
    assert new["superseded_by"] is None


def test_expired_and_future_nodes(tmp_path: Path):
    bundle = _make_bundle(
        tmp_path,
        {
            "index.md": "# I\n",
            "old-offer.md": _EXPIRED,
            "future-plan.md": _FUTURE,
        },
    )
    graph = build_graph(bundle)
    assert _node(graph, "old-offer")["temporal_status"] == "expired"
    assert _node(graph, "future-plan")["temporal_status"] == "not_yet_valid"
    assert _node(graph, "old-offer")["superseded_by"] is None


def test_plain_node_is_current(tmp_path: Path):
    bundle = _make_bundle(tmp_path, {"index.md": "# I\n", "a.md": _PLAIN})
    graph = build_graph(bundle)
    node = _node(graph, "a")
    assert node["temporal_status"] == "current"
    assert node["superseded_by"] is None


# ---------------------------------------------------------------------------
# temporal_mark / mermaid
# ---------------------------------------------------------------------------


def test_temporal_mark_vocabulary():
    assert temporal_mark({"temporal_status": "current"}) is None
    assert temporal_mark({}) is None  # hand-built node: unchanged
    assert (
        temporal_mark({"temporal_status": "superseded", "superseded_by": "new"})
        == "superseded by new"
    )
    assert temporal_mark({"temporal_status": "superseded"}) == "superseded"
    assert temporal_mark({"temporal_status": "expired"}) == "expired"
    assert temporal_mark({"temporal_status": "not_yet_valid"}) == "not yet valid"


def test_mermaid_marks_superseded_node_only(tmp_path: Path):
    bundle = _make_bundle(
        tmp_path, {"index.md": "# I\n", "old.md": _OLD, "new.md": _NEW}
    )
    chart = mermaid_flowchart(build_graph(bundle))
    assert "(superseded by new)" in chart
    assert chart.count("superseded by new") == 1
    # The current node's label has no temporal marker.
    assert '["new — New Policy"]' in chart


def test_mermaid_current_only_graph_unchanged(tmp_path: Path):
    bundle = _make_bundle(tmp_path, {"index.md": "# I\n", "a.md": _PLAIN})
    chart = mermaid_flowchart(build_graph(bundle))
    assert chart == 'flowchart LR\n    n_a["a — Plain Note"]\n'


# ---------------------------------------------------------------------------
# CLI: json + text
# ---------------------------------------------------------------------------


def test_graph_json_includes_temporal_status(tmp_path: Path):
    bundle = _make_bundle(
        tmp_path, {"index.md": "# I\n", "old.md": _OLD, "new.md": _NEW}
    )
    result = runner.invoke(
        app, ["graph", str(bundle.root), "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    old = next(n for n in payload["nodes"] if n["id"] == "old")
    assert old["temporal_status"] == "superseded"
    assert old["superseded_by"] == "new"


def test_graph_text_lists_non_current_concepts(tmp_path: Path):
    bundle = _make_bundle(
        tmp_path, {"index.md": "# I\n", "old.md": _OLD, "new.md": _NEW}
    )
    result = runner.invoke(app, ["graph", str(bundle.root)])
    assert result.exit_code == 0, result.output
    assert "Non-current concepts (1):" in result.output
    assert "  - old (superseded by new)" in result.output


def test_graph_text_plain_bundle_has_no_non_current_section(tmp_path: Path):
    bundle = _make_bundle(tmp_path, {"index.md": "# I\n", "a.md": _PLAIN})
    result = runner.invoke(app, ["graph", str(bundle.root)])
    assert result.exit_code == 0, result.output
    assert "Non-current" not in result.output
