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

    # Security default: read-only — only the eight read tools registered.
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


class TestMcpNetworkAuth:
    """Fix 7: sse / streamable-http require a bearer token; stdio does not."""

    def test_token_precedence(self, monkeypatch):
        from okfsmith.mcp_server import server as mcp_server

        monkeypatch.delenv(mcp_server.MCP_TOKEN_ENV_VAR, raising=False)
        token, source = mcp_server._resolve_mcp_token(None)
        assert source == "generated" and len(token) >= 32

        monkeypatch.setenv(mcp_server.MCP_TOKEN_ENV_VAR, "env-token")
        token, source = mcp_server._resolve_mcp_token(None)
        assert (token, source) == ("env-token", "env")

        token, source = mcp_server._resolve_mcp_token("flag-token")
        assert (token, source) == ("flag-token", "flag")

    def test_generated_tokens_are_unique(self, monkeypatch):
        from okfsmith.mcp_server import server as mcp_server

        monkeypatch.delenv(mcp_server.MCP_TOKEN_ENV_VAR, raising=False)
        t1, _ = mcp_server._resolve_mcp_token(None)
        t2, _ = mcp_server._resolve_mcp_token(None)
        assert t1 != t2

    def test_bearer_middleware(self):
        import anyio

        from okfsmith.mcp_server import server as mcp_server

        async def ok_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"ok"})

        async def call(app, headers):
            status = {}

            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(msg):
                if msg["type"] == "http.response.start":
                    status["code"] = msg["status"]

            scope = {"type": "http", "headers": headers}
            await app(scope, receive, send)
            return status["code"]

        wrapped = mcp_server._BearerAuthMiddleware(ok_app, "s3cret")
        assert anyio.run(call, wrapped, []) == 401
        assert anyio.run(call, wrapped, [(b"authorization", b"Bearer wrong")]) == 401
        assert anyio.run(
            call, wrapped, [(b"authorization", b"Bearer s3cret")]) == 200

    def test_bearer_middleware_lifespan_passthrough(self):
        import anyio

        from okfsmith.mcp_server import server as mcp_server

        seen = {}

        async def inner(scope, receive, send):
            seen["type"] = scope["type"]

        async def receive():
            return {"type": "lifespan.startup"}

        async def send(msg):
            pass

        wrapped = mcp_server._BearerAuthMiddleware(inner, "s3cret")
        anyio.run(wrapped, {"type": "lifespan", "headers": []}, receive, send)
        assert seen["type"] == "lifespan"

    def test_serve_http_enforces_auth(self, monkeypatch, tmp_path):
        """serve() with sse wraps the app in auth and never calls run()."""
        from okfsmith.mcp_server import server as mcp_server

        calls = {}
        monkeypatch.setattr(
            mcp_server, "_serve_http",
            lambda server, transport, **kw: calls.update(kw) or calls.update(
                {"transport": transport}),
        )
        mcp_server.serve(FIXTURE_BUNDLE, "sse", auth_token="t",
                         host="127.0.0.1", port=8123)
        assert calls["transport"] == "sse"
        assert calls["auth_token"] == "t"

    def test_serve_stdio_needs_no_auth(self, monkeypatch):
        from okfsmith.mcp_server import server as mcp_server

        def boom(*a, **k):
            raise AssertionError("_serve_http must not run for stdio")

        monkeypatch.setattr(mcp_server, "_serve_http", boom)
        ran = {}
        monkeypatch.setattr(
            mcp_server, "build_server",
            lambda *a, **k: type("S", (), {"run": lambda self, **kw: ran.update(kw)})(),
        )
        mcp_server.serve(FIXTURE_BUNDLE, "stdio")
        assert ran.get("transport") == "stdio"


class TestSearchAsOf:
    """MCP ``search`` temporal replay (``as_of``).

    Parity with the ``okfsmith search --as-of`` CLI flag: an agent can ask
    what the bundle said about a topic at a past (or future) instant. The
    bundle below has ``policy-v1`` superseded by ``policy-v2``, whose
    ``valid_from`` is 2026-10-20.
    """

    @pytest.fixture()
    def temporal_tools(self, tmp_path: Path) -> BundleTools:
        bundle = Bundle(tmp_path)
        bundle.write_concept(
            "policy-v1",
            {"title": "Refund Policy v1", "type": "policy"},
            "The old refund policy allows returns within 14 days of purchase.",
        )
        bundle.write_concept(
            "policy-v2",
            {
                "title": "Refund Policy v2",
                "type": "policy",
                "supersedes": ["policy-v1"],
                "valid_from": "2026-10-20",
            },
            "The new refund policy allows returns within 30 days of purchase.",
        )
        return BundleTools(bundle)

    def test_default_search_hides_superseded(self, temporal_tools: BundleTools) -> None:
        out = temporal_tools.search("refund")
        assert "policy-v2" in out
        assert "policy-v1" not in out
        assert "1 superseded concept(s) hidden" in out

    def test_as_of_replays_past_state(self, temporal_tools: BundleTools) -> None:
        # Before policy-v2's valid_from, the old policy was the current one.
        out = temporal_tools.search("refund", as_of="2026-10-01")
        assert "policy-v1" in out
        # current hits rank before demoted (not-yet-valid) ones
        assert out.index("policy-v1") < out.index("policy-v2")
        assert "superseded concept(s) hidden" not in out
        # the replay instant is labeled honestly, like the CLI envelope
        assert "as of 2026-10-01" in out

    def test_as_of_future_keeps_supersession(
        self, temporal_tools: BundleTools
    ) -> None:
        out = temporal_tools.search("refund", as_of="2027-01-01")
        assert "policy-v2" in out
        assert "policy-v1" not in out
        assert "1 superseded concept(s) hidden" in out

    def test_as_of_accepts_datetime(self, temporal_tools: BundleTools) -> None:
        out = temporal_tools.search("refund", as_of="2026-10-01T12:00:00Z")
        assert "policy-v1" in out

    def test_as_of_invalid_value_returns_error_not_exception(
        self, temporal_tools: BundleTools
    ) -> None:
        # the tools' "never an exception" contract covers as_of too
        out = temporal_tools.search("refund", as_of="not-a-date")
        assert out.startswith("Error:")
        assert "ISO-8601" in out

    def test_as_of_blank_is_ignored(self, temporal_tools: BundleTools) -> None:
        out = temporal_tools.search("refund", as_of="  ")
        assert "policy-v2" in out
        assert "policy-v1" not in out

    def test_as_of_combines_with_include_superseded(
        self, temporal_tools: BundleTools
    ) -> None:
        out = temporal_tools.search(
            "refund", as_of="2026-10-01", include_superseded=True
        )
        assert "policy-v1" in out
        assert "policy-v2" in out
        assert "superseded concept(s) hidden" not in out


class TestSearchFilters:
    """``search`` type/tier filters: MCP parity with the CLI (0.12.0).

    The CLI's ``--type`` / ``--tier`` flags filter before the ``limit`` cut
    (0.11.1); the MCP tool had no such parameters, so agent callers could
    not narrow a search at all. These tests pin the new ``type_filter`` /
    ``tier_filter`` parameters, including the filter-before-limit case.
    """

    @pytest.fixture()
    def filter_tools(self, tmp_path: Path) -> BundleTools:
        bundle = Bundle(tmp_path)
        bundle.write_concept(
            "notes/alpha",
            {"type": "Note", "title": "Alpha"},
            "refund " * 10,
        )
        bundle.write_concept(
            "guides/beta",
            {
                "type": "Guide",
                "title": "Beta",
                "verified": [{"by": "human:alice"}],
            },
            "refund policy note",
        )
        bundle.write_concept(
            "notes/gamma",
            {
                "type": "Note",
                "title": "Gamma",
                "verified": [{"by": "process:nightly"}],
            },
            "refund",
        )
        return BundleTools(bundle)

    def test_type_filter_narrows(self, filter_tools: BundleTools) -> None:
        out = filter_tools.search("refund", type_filter="guide")
        assert "guides/beta" in out
        assert "notes/alpha" not in out
        assert "notes/gamma" not in out

    def test_type_filter_case_insensitive(
        self, filter_tools: BundleTools
    ) -> None:
        out = filter_tools.search("refund", type_filter="GUIDE")
        assert "guides/beta" in out
        assert "notes/alpha" not in out

    def test_tier_filter_human_reviewed(
        self, filter_tools: BundleTools
    ) -> None:
        out = filter_tools.search("refund", tier_filter="human-reviewed")
        assert "guides/beta" in out
        assert "notes/alpha" not in out
        assert "notes/gamma" not in out

    def test_tier_filter_machine_confirmed(
        self, filter_tools: BundleTools
    ) -> None:
        out = filter_tools.search("refund", tier_filter="machine-confirmed")
        assert "notes/gamma" in out
        assert "guides/beta" not in out

    def test_filters_apply_before_limit(
        self, filter_tools: BundleTools
    ) -> None:
        # Unfiltered, notes/alpha ranks first; the guide is found anyway
        # when the filter is on, even with limit=1.
        out = filter_tools.search("refund", limit=1)
        assert "notes/alpha" in out
        assert "guides/beta" not in out
        out = filter_tools.search("refund", limit=1, type_filter="guide")
        assert "guides/beta" in out

    def test_both_filters_combine(
        self, filter_tools: BundleTools
    ) -> None:
        out = filter_tools.search(
            "refund", type_filter="note", tier_filter="machine-confirmed"
        )
        assert "notes/gamma" in out
        assert "notes/alpha" not in out
        assert "guides/beta" not in out

    def test_unknown_tier_returns_error_not_exception(
        self, filter_tools: BundleTools
    ) -> None:
        # the tools' "never an exception" contract covers tier_filter too
        out = filter_tools.search("refund", tier_filter="bogus")
        assert out.startswith("Error:")
        assert "human-reviewed" in out

    def test_blank_filters_ignored(
        self, filter_tools: BundleTools
    ) -> None:
        out = filter_tools.search("refund", type_filter="  ", tier_filter="")
        assert "notes/alpha" in out
        assert "guides/beta" in out
        assert "notes/gamma" in out

    def test_filter_with_no_match(self, filter_tools: BundleTools) -> None:
        out = filter_tools.search("refund", type_filter="table")
        assert "No concepts match" in out
