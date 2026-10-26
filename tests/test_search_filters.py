"""Tests for ``search`` --type/--tier filters applying before the limit cut.

Regression: the CLI used to truncate ``search_bundle_detailed`` hits to
``--limit`` and only then drop rows failing ``--type``/``--tier``, so
``search kb refund --type guide -n 1`` returned nothing when the only
guide ranked second. Filters now live in the engine
(``search_bundle_detailed``), applied to every partition group before
truncation, and ``superseded_hidden`` counts only filter-passing hits.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from okfsmith.cli.app import app
from okfsmith.core.bundle import Bundle
from okfsmith.search import search_bundle, search_bundle_detailed

runner = CliRunner()
WIDE = {"COLUMNS": "200"}


def _bundle(tmp_path: Path) -> Bundle:
    bundle = Bundle(tmp_path / "kb")
    bundle.write_concept(
        "notes/alpha",
        {"type": "Note", "title": "Alpha"},
        "refund " * 10,
    )
    bundle.write_concept(
        "guides/beta",
        {"type": "Guide", "title": "Beta",
         "verified": [{"by": "human:alice"}]},
        "refund policy note",
    )
    bundle.write_concept(
        "notes/gamma",
        {"type": "Note", "title": "Gamma",
         "verified": [{"by": "process:nightly"}]},
        "refund",
    )
    (bundle.root / "index.md").write_text("# Index\n", encoding="utf-8")
    return bundle


def _ids(hits) -> list[str]:
    return [concept.id for _, concept in hits]


class TestFilterBeforeLimit:
    def test_ranking_without_filter_unchanged(self, tmp_path):
        bundle = _bundle(tmp_path)
        assert _ids(search_bundle_detailed(bundle, "refund", limit=1).hits) == [
            "notes/alpha"
        ]

    def test_type_filter_finds_lower_ranked_match(self, tmp_path):
        bundle = _bundle(tmp_path)
        result = search_bundle_detailed(
            bundle, "refund", limit=1, type_filter="guide"
        )
        assert _ids(result.hits) == ["guides/beta"]

    def test_type_filter_case_insensitive(self, tmp_path):
        bundle = _bundle(tmp_path)
        result = search_bundle_detailed(
            bundle, "refund", limit=1, type_filter="GUIDE"
        )
        assert _ids(result.hits) == ["guides/beta"]

    def test_tier_filter_finds_lower_ranked_match(self, tmp_path):
        bundle = _bundle(tmp_path)
        result = search_bundle_detailed(
            bundle, "refund", limit=1, tier_filter="human-reviewed"
        )
        assert _ids(result.hits) == ["guides/beta"]

    def test_search_bundle_passes_filters_through(self, tmp_path):
        bundle = _bundle(tmp_path)
        assert _ids(search_bundle(bundle, "refund", limit=1,
                                  type_filter="guide")) == ["guides/beta"]

    def test_filter_with_no_match_returns_empty(self, tmp_path):
        bundle = _bundle(tmp_path)
        result = search_bundle_detailed(
            bundle, "refund", limit=10, type_filter="NoSuchType"
        )
        assert result.hits == []
        assert result.superseded_hidden == 0


def _superseding_bundle(tmp_path: Path) -> Bundle:
    bundle = Bundle(tmp_path / "kb")
    bundle.write_concept("cur", {"type": "Note", "title": "Cur"}, "refund")
    bundle.write_concept(
        "old-guide", {"type": "Guide", "title": "Old guide"}, "refund"
    )
    bundle.write_concept(
        "new-guide",
        {"type": "Guide", "title": "New guide", "supersedes": "old-guide"},
        "refund",
    )
    bundle.write_concept(
        "old-note", {"type": "Note", "title": "Old note"}, "refund"
    )
    bundle.write_concept(
        "new-note",
        {"type": "Note", "title": "New note", "supersedes": "old-note"},
        "refund",
    )
    (bundle.root / "index.md").write_text("# Index\n", encoding="utf-8")
    return bundle


class TestHiddenCountHonorsFilter:
    def test_hidden_counts_all_superseded_without_filter(self, tmp_path):
        bundle = _superseding_bundle(tmp_path)
        result = search_bundle_detailed(bundle, "refund", limit=10)
        assert result.superseded_hidden == 2

    def test_hidden_counts_only_filter_passing_superseded(self, tmp_path):
        bundle = _superseding_bundle(tmp_path)
        result = search_bundle_detailed(
            bundle, "refund", limit=10, type_filter="guide"
        )
        assert result.superseded_hidden == 1

    def test_include_superseded_with_filter_shows_match_last(self, tmp_path):
        bundle = _superseding_bundle(tmp_path)
        result = search_bundle_detailed(
            bundle, "refund", limit=10, type_filter="guide",
            include_superseded=True,
        )
        assert _ids(result.hits) == ["new-guide", "old-guide"]
        assert result.superseded_hidden == 0


class TestCliEndToEnd:
    def test_cli_type_filter_before_limit(self, tmp_path):
        bundle = _bundle(tmp_path)
        result = runner.invoke(
            app,
            ["search", str(bundle.root), "refund", "--type", "guide",
             "-n", "1", "--format", "json"],
            env=WIDE,
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["count"] == 1
        assert payload["results"][0]["id"] == "guides/beta"

    def test_cli_tier_filter_before_limit(self, tmp_path):
        bundle = _bundle(tmp_path)
        result = runner.invoke(
            app,
            ["search", str(bundle.root), "refund", "--tier", "human-reviewed",
             "-n", "1", "--format", "json"],
            env=WIDE,
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["count"] == 1
        assert payload["results"][0]["id"] == "guides/beta"
