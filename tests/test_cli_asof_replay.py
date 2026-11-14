"""``--as-of`` temporal replay for list / read / graph (0.28.0).

``search`` / ``eval`` / chat / MCP already replay at a past/future instant;
``list``, ``read`` and ``graph`` evaluated temporal status only at *now* —
so "what did the bundle believe in 2019?" had no answer on those surfaces.
These tests pin the replay:

- ``list`` / ``read`` / ``graph`` (json, text, mermaid, html) evaluate
  validity windows at the ``--as-of`` instant: a concept whose window had
  not yet closed reads ``current`` there, expired now.
- the JSON envelopes name the evaluated instant (``as_of``), like search.
- the HTML viewer labels a replay in its header stats ("as of ...") and
  never labels a plain (no-flag) render.
- a garbage ``--as-of`` is a usage error (exit 2), like search/eval.
- without the flag, behaviour is unchanged: plain bundles print
  byte-identical output (covered by the existing temporal tests); the new
  JSON ``as_of`` key is the only addition, matching search's envelope.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from typer.testing import CliRunner

from okfsmith.cli.app import app
from okfsmith.core.bundle import Bundle
from okfsmith.core.temporal import parse_temporal
from okfsmith.links import build_graph
from okfsmith.viz import render_html

runner = CliRunner()


def _plain(output: str) -> str:
    """Strip ANSI escapes and collapse whitespace in CLI output.

    On GitHub Actions Typer colorizes and wraps its rich error panel
    (it forces terminal output when ``GITHUB_ACTIONS`` is set), so a
    verbatim message substring never matches; the wording is what the
    test pins, not the wrapping.
    """
    return " ".join(re.sub(r"\x1b\[[0-9;]*m", "", output).split())


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


def _temporal_bundle(tmp_path: Path) -> Path:
    return _make_bundle(
        tmp_path,
        {
            "index.md": "# I\n",
            "old.md": _OLD,
            "new.md": _NEW,
            "old-offer.md": _EXPIRED,
            "future-plan.md": _FUTURE,
        },
    )


def _statuses(payload: dict) -> dict[str, str]:
    return {c["id"]: c["temporal_status"] for c in payload["concepts"]}


def _node(graph: dict, concept_id: str) -> dict:
    return next(n for n in graph["nodes"] if n["id"] == concept_id)


def _embedded_model(text: str) -> dict:
    match = re.search(r"const BUNDLE = (.*?);\n", text, re.DOTALL)
    assert match, "embedded model not found in viz html"
    return json.loads(match.group(1).replace("<\\/", "</"))


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_as_of_replays_validity_window(tmp_path: Path):
    root = _temporal_bundle(tmp_path)
    result = runner.invoke(
        app, ["list", str(root), "--as-of", "2019-06-01", "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["as_of"] == "2019-06-01T00:00:00+00:00"
    statuses = _statuses(payload)
    # The offer's window had not closed yet in June 2019.
    assert statuses["old-offer"] == "current"
    # Supersession is not time-travelled away: `new` still supersedes `old`.
    assert statuses["old"] == "superseded"
    # The future plan was not yet valid even then.
    assert statuses["future-plan"] == "not_yet_valid"


def test_list_now_marks_expired(tmp_path: Path):
    root = _temporal_bundle(tmp_path)
    result = runner.invoke(app, ["list", str(root), "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "as_of" in payload
    assert _statuses(payload)["old-offer"] == "expired"


def test_list_as_of_invalid_value_is_usage_error(tmp_path: Path):
    root = _temporal_bundle(tmp_path)
    result = runner.invoke(app, ["list", str(root), "--as-of", "not-a-date"])
    assert result.exit_code == 2
    assert (
        "--as-of 'not-a-date' is not an ISO-8601 date or datetime."
        in _plain(result.output)
    )


def test_list_as_of_text_shows_replayed_valid_column(tmp_path: Path):
    root = _temporal_bundle(tmp_path)
    result = runner.invoke(app, ["list", str(root), "--as-of", "2019-06-01"])
    assert result.exit_code == 0, result.output
    # At the replay instant the offer is current, so its Valid cell reads
    # "current" — not "expired" as it does at now.
    assert "expired" not in result.output


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


def test_read_as_of_replays_badge_and_json(tmp_path: Path):
    root = _temporal_bundle(tmp_path)
    result = runner.invoke(
        app,
        ["read", str(root), "old-offer", "--as-of", "2019-06-01", "--format", "json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["temporal_status"] == "current"
    assert payload["as_of"] == "2019-06-01T00:00:00+00:00"

    result = runner.invoke(
        app, ["read", str(root), "old-offer", "--as-of", "2019-06-01"]
    )
    assert result.exit_code == 0, result.output
    assert "[temporal: current (valid — → 2020-01-01)]" in result.output


def test_read_as_of_future_window_becomes_current(tmp_path: Path):
    root = _temporal_bundle(tmp_path)
    result = runner.invoke(
        app,
        ["read", str(root), "future-plan", "--as-of", "3000-01-01", "--format", "json"],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["temporal_status"] == "current"


def test_read_now_badge_unchanged(tmp_path: Path):
    root = _temporal_bundle(tmp_path)
    result = runner.invoke(app, ["read", str(root), "old-offer"])
    assert result.exit_code == 0, result.output
    assert "[temporal: expired (valid_until 2020-01-01 has passed)]" in result.output
    result = runner.invoke(
        app, ["read", str(root), "old-offer", "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["temporal_status"] == "expired"
    assert "as_of" in payload


def test_read_as_of_invalid_value_is_usage_error(tmp_path: Path):
    root = _temporal_bundle(tmp_path)
    result = runner.invoke(
        app, ["read", str(root), "old-offer", "--as-of", "yesterday-ish"]
    )
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# graph: build_graph / json / text / mermaid
# ---------------------------------------------------------------------------


def test_build_graph_as_of_parameter(tmp_path: Path):
    bundle = Bundle.load(_temporal_bundle(tmp_path))
    graph = build_graph(bundle, as_of=parse_temporal("2019-06-01"))
    assert _node(graph, "old-offer")["temporal_status"] == "current"
    assert _node(graph, "old")["temporal_status"] == "superseded"
    graph_now = build_graph(bundle)
    assert _node(graph_now, "old-offer")["temporal_status"] == "expired"


def test_graph_json_as_of(tmp_path: Path):
    root = _temporal_bundle(tmp_path)
    result = runner.invoke(
        app, ["graph", str(root), "--as-of", "2019-06-01", "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["as_of"] == "2019-06-01T00:00:00+00:00"
    assert _node(payload, "old-offer")["temporal_status"] == "current"
    assert _node(payload, "future-plan")["temporal_status"] == "not_yet_valid"


def test_graph_text_as_of_omits_replayed_concept(tmp_path: Path):
    root = _temporal_bundle(tmp_path)
    result = runner.invoke(app, ["graph", str(root), "--as-of", "2019-06-01"])
    assert result.exit_code == 0, result.output
    assert "Non-current concepts (2):" in result.output
    assert "future-plan" in result.output
    assert "old (superseded by new)" in result.output
    assert "old-offer" not in result.output.split("Non-current concepts")[1].split(
        "Orphans"
    )[0]


def test_graph_mermaid_as_of(tmp_path: Path):
    root = _temporal_bundle(tmp_path)
    result = runner.invoke(
        app, ["graph", str(root), "--as-of", "2019-06-01", "--format", "mermaid"]
    )
    assert result.exit_code == 0, result.output
    assert "old-offer" in result.output
    assert "Old Offer (expired" not in result.output
    assert "Future Plan (not yet valid)" in result.output


def test_graph_as_of_invalid_value_is_usage_error(tmp_path: Path):
    root = _temporal_bundle(tmp_path)
    result = runner.invoke(
        app, ["graph", str(root), "--as-of", "nope", "--format", "json"]
    )
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# graph: html viewer
# ---------------------------------------------------------------------------


def test_render_html_as_of_parameter(tmp_path: Path):
    root = _temporal_bundle(tmp_path)
    text = render_html(
        root, tmp_path / "viz.html", as_of=parse_temporal("2019-06-01")
    ).read_text(encoding="utf-8")
    model = _embedded_model(text)
    assert _node(model, "old-offer")["temporal_status"] == "current"
    assert _node(model, "future-plan")["temporal_status"] == "not_yet_valid"
    assert "as of 2019-06-01" in text


def test_graph_html_cli_as_of_labels_replay(tmp_path: Path):
    root = _temporal_bundle(tmp_path)
    out = tmp_path / "graph.html"
    result = runner.invoke(
        app,
        ["graph", str(root), "--format", "html", "--output", str(out),
         "--as-of", "2019-06-01"],
    )
    assert result.exit_code == 0, result.output
    text = out.read_text(encoding="utf-8")
    assert _node(_embedded_model(text), "old-offer")["temporal_status"] == "current"
    assert "as of 2019-06-01" in text


def test_graph_html_without_as_of_has_no_replay_label(tmp_path: Path):
    root = _temporal_bundle(tmp_path)
    text = render_html(root, tmp_path / "viz.html").read_text(encoding="utf-8")
    assert "as of" not in text
    assert _node(_embedded_model(text), "old-offer")["temporal_status"] == "expired"
