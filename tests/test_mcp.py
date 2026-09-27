"""Tests for the okfsmith MCP server.

The underlying tool functions (``BundleTools`` methods) are called directly —
no live MCP transport is needed. ``build_server`` is additionally exercised
to prove the five tools register with their docstrings.

Requires the ``mcp`` extra (fastmcp). If it is not installed, everything
except ``test_build_server_registers_tools`` is skipped with a clear reason.
"""

from __future__ import annotations

from pathlib import Path

import pytest

fastmcp = pytest.importorskip("fastmcp", reason="mcp extra not installed")

from okfsmith.core import Bundle  # noqa: E402
from okfsmith.mcp_server.server import BundleTools, build_server  # noqa: E402

FIXTURE_BUNDLE = Path(__file__).resolve().parent.parent / ".contract" / "fixtures" / "valid"


@pytest.fixture()
def tools() -> BundleTools:
    return BundleTools(Bundle.load(FIXTURE_BUNDLE))


def test_fixture_bundle_present() -> None:
    assert FIXTURE_BUNDLE.is_dir(), f"fixture bundle missing: {FIXTURE_BUNDLE}"


def test_search_finds_known_concepts(tools: BundleTools) -> None:
    out = tools.search("revenue")
    assert "finance/revenue" in out
    assert "computations/revenue" in out
    # each hit carries type, trust tier, and a one-line description
    assert "human-reviewed" in out
    assert "BigQuery Table" in out
    assert "One row per completed customer order across all channels." in out


def test_search_ranking_prefers_title_matches(tools: BundleTools) -> None:
    out = tools.search("freshness")
    assert "incidents/playbook" in out
    first_hit = [line for line in out.splitlines() if line.startswith("- ")][0]
    assert "incidents/playbook" in first_hit


def test_search_no_match(tools: BundleTools) -> None:
    out = tools.search("zzz-no-such-word")
    assert "No concepts match" in out


def test_get_returns_frontmatter_and_body(tools: BundleTools) -> None:
    out = tools.get("finance/revenue")
    # frontmatter
    assert "type: BigQuery Table" in out
    assert "title: Customer Orders" in out
    assert "verified" in out
    assert "---" in out.splitlines()
    # body
    assert "# Schema" in out
    assert "gross profit table" in out


def test_get_missing_concept_returns_clean_error(tools: BundleTools) -> None:
    out = tools.get("does/not-exist")
    assert out.startswith("Error: concept")
    assert "not found" in out
    assert "does/not-exist" in out


def test_list_inventory(tools: BundleTools) -> None:
    out = tools.list()
    for concept_id in ("finance/revenue", "finance/profit", "computations/revenue", "incidents/playbook"):
        assert concept_id in out
    assert "human-reviewed" in out
    assert "machine-confirmed" in out
    assert "unverified" in out


def test_list_filter_type(tools: BundleTools) -> None:
    out = tools.list(filter_type="Metric")
    assert "finance/profit" in out
    assert "finance/revenue" not in out


def test_list_limit(tools: BundleTools) -> None:
    out = tools.list(limit=1)
    assert len([line for line in out.splitlines() if line.startswith("- ")]) == 1


def test_neighbors_shows_links(tools: BundleTools) -> None:
    out = tools.neighbors("finance/profit")
    assert "## Outgoing" in out
    assert "## Incoming" in out
    # outgoing: profit links to the revenue computation with prose-derived text
    assert "computations/revenue" in out
    assert "the revenue computation" in out
    # incoming: finance/revenue links back ("gross profit table")
    assert "finance/revenue" in out
    assert "gross profit table" in out


def test_neighbors_missing_concept(tools: BundleTools) -> None:
    out = tools.neighbors("nope/missing")
    assert out.startswith("Error: concept")


def test_index_returns_root_index(tools: BundleTools) -> None:
    out = tools.index()
    assert "# OKF Test Bundle" in out
    assert "finance/revenue" in out


def test_build_server_registers_tools() -> None:
    import asyncio

    server = build_server(FIXTURE_BUNDLE)
    registered = asyncio.run(server._list_tools())
    tool_names = {t.name for t in registered}
    assert tool_names == {
        "index",
        "list",
        "search",
        "get",
        "neighbors",
        "traverse",
        "provenance",
        "diff",
    }
    # docstrings are the agent's UI — every tool must carry one
    for tool in registered:
        assert tool.description and len(tool.description.split()) > 10, tool.name


def test_build_server_missing_bundle() -> None:
    with pytest.raises(FileNotFoundError):
        build_server(FIXTURE_BUNDLE / "does-not-exist")
