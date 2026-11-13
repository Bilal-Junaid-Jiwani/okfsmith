"""Viz HTML graph shows temporal status (0.27.0).

``search`` / ``list`` / ``read``, the dashboard graph, MCP, and the CLI
``graph`` formats already surface whether a concept is current, superseded,
expired, or not yet valid; the interactive ``viz.html`` viewer did not — a
superseded concept rendered as a live node with no hint it was out of date.
These tests pin the fix:

- viz nodes carry ``temporal_status`` + ``superseded_by`` in the embedded
  model (same instant, same vocabulary as ``links.build_graph``).
- non-current nodes are struck through on the canvas (shape channel, never
  color alone), get a temporal badge in the detail panel, and are counted in
  the header stats; the legend explains the strike-through.
- a plain bundle is unchanged: no non-current count in the stats, no
  strike-through legend row.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from typer.testing import CliRunner

from okfsmith.cli.app import app
from okfsmith.viz import render_html

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


def _make_bundle(tmp_path: Path, files: dict) -> Path:
    root = tmp_path / "kb"
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def _embedded_model(html_text: str) -> dict:
    """Parse the ``const BUNDLE = {...};`` payload out of rendered viz.html."""
    match = re.search(r"const BUNDLE = (.*?);\n", html_text, re.DOTALL)
    assert match, "embedded BUNDLE payload not found in viz.html"
    # render_html escapes "</" as "<\/" inside the payload; undo it.
    return json.loads(match.group(1).replace("<\\/", "</"))


def _node(model: dict, concept_id: str) -> dict:
    return next(n for n in model["nodes"] if n["id"] == concept_id)


# ---------------------------------------------------------------------------
# embedded model
# ---------------------------------------------------------------------------


def test_viz_nodes_carry_temporal_status(tmp_path: Path):
    root = _make_bundle(
        tmp_path,
        {
            "index.md": "# I\n",
            "old.md": _OLD,
            "new.md": _NEW,
            "old-offer.md": _EXPIRED,
            "future-plan.md": _FUTURE,
        },
    )
    text = render_html(root, tmp_path / "viz.html").read_text(encoding="utf-8")
    model = _embedded_model(text)
    old = _node(model, "old")
    assert old["temporal_status"] == "superseded"
    assert old["superseded_by"] == "new"
    assert _node(model, "new")["temporal_status"] == "current"
    assert _node(model, "new")["superseded_by"] is None
    assert _node(model, "old-offer")["temporal_status"] == "expired"
    assert _node(model, "old-offer")["superseded_by"] is None
    assert _node(model, "future-plan")["temporal_status"] == "not_yet_valid"


def test_viz_plain_node_is_current(tmp_path: Path):
    root = _make_bundle(tmp_path, {"index.md": "# I\n", "a.md": _PLAIN})
    text = render_html(root, tmp_path / "viz.html").read_text(encoding="utf-8")
    node = _node(_embedded_model(text), "a")
    assert node["temporal_status"] == "current"
    assert node["superseded_by"] is None


# ---------------------------------------------------------------------------
# viewer chrome: stats, legend, detail badge, screen-reader list
# ---------------------------------------------------------------------------


def test_viz_header_counts_non_current(tmp_path: Path):
    root = _make_bundle(
        tmp_path,
        {
            "index.md": "# I\n",
            "old.md": _OLD,
            "new.md": _NEW,
            "old-offer.md": _EXPIRED,
            "future-plan.md": _FUTURE,
        },
    )
    text = render_html(root, tmp_path / "viz.html").read_text(encoding="utf-8")
    # Three non-current nodes: superseded old, expired offer, future plan.
    assert "3 non-current" in text
    assert "Non-current concepts are struck through" in text


def test_viz_plain_bundle_stats_unchanged(tmp_path: Path):
    root = _make_bundle(tmp_path, {"index.md": "# I\n", "a.md": _PLAIN})
    text = render_html(root, tmp_path / "viz.html").read_text(encoding="utf-8")
    # The viewer source always mentions non-current nodes (drawing code,
    # legend builder); the *visible chrome* must not: header stats and the
    # canvas aria-label stay exactly as before.
    stats = re.search(r'<span class="stats">(.*?)</span>', text).group(1)
    assert "non-current" not in stats
    aria = re.search(r'aria-label="([^"]*)"', text).group(1)
    assert "struck through" not in aria


def test_viz_temporal_chrome_present(tmp_path: Path):
    root = _make_bundle(
        tmp_path, {"index.md": "# I\n", "old.md": _OLD, "new.md": _NEW}
    )
    text = render_html(root, tmp_path / "viz.html").read_text(encoding="utf-8")
    # Struck-through drawing + detail-panel badge + legend explanation.
    assert "non-current: struck through" in text
    assert "badge temporal" in text
    assert "temporalMark(n)" in text
    assert "non-current concept" in text
    assert "superseded by " in text


# ---------------------------------------------------------------------------
# CLI end to end: graph --format html
# ---------------------------------------------------------------------------


def test_graph_html_cli_writes_temporal_viz(tmp_path: Path):
    root = _make_bundle(
        tmp_path, {"index.md": "# I\n", "old.md": _OLD, "new.md": _NEW}
    )
    out = tmp_path / "graph.html"
    result = runner.invoke(
        app, ["graph", str(root), "--format", "html", "--output", str(out)]
    )
    assert result.exit_code == 0, result.output
    text = out.read_text(encoding="utf-8")
    old = _node(_embedded_model(text), "old")
    assert old["temporal_status"] == "superseded"
    assert old["superseded_by"] == "new"
    assert "1 non-current" in text
