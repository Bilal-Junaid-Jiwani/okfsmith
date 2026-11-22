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


def test_list_tier_filter(tools: BundleTools) -> None:
    # Fixture tiers: finance/revenue + computations/revenue are
    # human-reviewed, finance/profit is machine-confirmed, and
    # incidents/playbook is unverified.
    out = tools.list(tier_filter="human-reviewed")
    assert "finance/revenue" in out
    assert "computations/revenue" in out
    assert "finance/profit" not in out
    assert "incidents/playbook" not in out


def test_list_tier_filter_case_insensitive_and_blank(tools: BundleTools) -> None:
    out = tools.list(tier_filter="HUMAN-REVIEWED")
    assert "finance/revenue" in out
    assert "finance/profit" not in out
    assert "incidents/playbook" in tools.list(tier_filter="  ")


def test_list_tier_filter_unknown_is_clean_error(tools: BundleTools) -> None:
    out = tools.list(tier_filter="gold")
    assert out.startswith("Error: `tier_filter`")
    assert "unverified" in out and "human-reviewed" in out


def test_list_tier_filter_combines_with_type(tools: BundleTools) -> None:
    out = tools.list(filter_type="BigQuery", tier_filter="human-reviewed")
    assert "finance/revenue" in out
    assert "computations/revenue" not in out
    out = tools.list(filter_type="Metric", tier_filter="human-reviewed")
    assert "No concepts found" in out


def test_list_tier_filter_applies_before_limit(tools: BundleTools) -> None:
    # incidents/playbook is the only unverified concept and sorts last;
    # a limit-before-filter cut of 1 would drop it and return nothing.
    out = tools.list(tier_filter="unverified", limit=1)
    assert "incidents/playbook" in out
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

    # Security default: read-only — only the nine read tools registered.
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
        "validate",
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


class TestListAsOf:
    """MCP ``list`` temporal replay (``as_of``).

    Parity with the ``okfsmith list --as-of`` CLI flag (0.28.0) and the
    dashboard listing's ``?as_of=`` parameter (0.29.0): until now the MCP
    ``list`` tool evaluated temporal status only at now, so an agent
    asking "what did the bundle believe in October 2026?" got the
    present's answers on every row. Same bundle as ``TestSearchAsOf``:
    ``policy-v1`` superseded by ``policy-v2``, whose ``valid_from`` is
    2026-10-20.
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

    @staticmethod
    def _line(out: str, concept_id: str) -> str:
        return next(
            line
            for line in out.splitlines()
            if line.startswith(f"- **{concept_id}**")
        )

    def test_as_of_replays_past_state(self, temporal_tools: BundleTools) -> None:
        # Before policy-v2's valid_from, the old policy was the current one.
        out = temporal_tools.list(as_of="2026-10-01")
        assert "superseded" not in self._line(out, "policy-v1")
        assert "not yet valid" in self._line(out, "policy-v2")
        # the replay instant is labeled honestly, like the CLI envelope
        assert "as of 2026-10-01" in out

    def test_as_of_future_keeps_supersession(
        self, temporal_tools: BundleTools
    ) -> None:
        out = temporal_tools.list(as_of="2027-01-01")
        assert "superseded by `policy-v2`" in self._line(out, "policy-v1")
        assert "superseded" not in self._line(out, "policy-v2")

    def test_as_of_accepts_datetime(self, temporal_tools: BundleTools) -> None:
        out = temporal_tools.list(as_of="2026-10-01T12:00:00Z")
        assert "superseded" not in self._line(out, "policy-v1")
        assert "not yet valid" in self._line(out, "policy-v2")

    def test_as_of_invalid_value_returns_error_not_exception(
        self, temporal_tools: BundleTools
    ) -> None:
        # the tools' "never an exception" contract covers as_of too
        out = temporal_tools.list(as_of="not-a-date")
        assert out.startswith("Error:")
        assert "ISO-8601" in out

    def test_as_of_blank_is_ignored(self, temporal_tools: BundleTools) -> None:
        out = temporal_tools.list(as_of="  ")
        assert "superseded by `policy-v2`" in self._line(out, "policy-v1")

    def test_as_of_combines_with_filters(
        self, temporal_tools: BundleTools
    ) -> None:
        out = temporal_tools.list(filter_type="policy", as_of="2026-10-01")
        assert "policy-v1" in out
        assert "policy-v2" in out
        assert "superseded" not in self._line(out, "policy-v1")


class TestGetAsOf:
    """MCP ``get`` temporal replay (``as_of``).

    Parity with the ``okfsmith read --as-of`` CLI flag (0.28.0) and the
    dashboard concept detail's ``?as_of=`` parameter (0.29.0): until now
    the MCP ``get`` tool returned the document bare even for a superseded
    concept — an agent reading one concept in full got no temporal status
    at all, and no way to ask what the bundle believed about it at a past
    instant. Same bundle as ``TestSearchAsOf``: ``policy-v1`` superseded
    by ``policy-v2``, whose ``valid_from`` is 2026-10-20.
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

    def test_get_shows_temporal_note_at_now(
        self, temporal_tools: BundleTools
    ) -> None:
        # No as_of: the superseded concept is flagged at now, like list.
        out = temporal_tools.get("policy-v1")
        assert "superseded by `policy-v2`" in out
        assert "14 days of purchase" in out
        # A current concept stays bare (byte-identical default output).
        out2 = temporal_tools.get("policy-v2")
        assert "superseded" not in out2 and "Note:" not in out2
        assert "30 days of purchase" in out2

    def test_as_of_replays_past_state(self, temporal_tools: BundleTools) -> None:
        # Before policy-v2's valid_from, the old policy was the current one.
        out = temporal_tools.get("policy-v1", as_of="2026-10-01")
        assert "superseded" not in out
        assert "14 days of purchase" in out
        # The replay instant is labeled honestly, like the CLI envelope.
        assert "as of 2026-10-01" in out
        # The not-yet-valid successor is flagged at the replay instant.
        out2 = temporal_tools.get("policy-v2", as_of="2026-10-01")
        assert "not yet valid" in out2
        assert "as of 2026-10-01" in out2

    def test_as_of_future_keeps_supersession(
        self, temporal_tools: BundleTools
    ) -> None:
        out = temporal_tools.get("policy-v1", as_of="2027-01-01")
        assert "superseded by `policy-v2`" in out
        assert "as of 2027-01-01" in out
        assert "superseded" not in temporal_tools.get(
            "policy-v2", as_of="2027-01-01"
        )

    def test_as_of_accepts_datetime(self, temporal_tools: BundleTools) -> None:
        out = temporal_tools.get("policy-v1", as_of="2026-10-01T12:00:00Z")
        assert "superseded" not in out
        assert "as of 2026-10-01" in out

    def test_as_of_invalid_value_returns_error_not_exception(
        self, temporal_tools: BundleTools
    ) -> None:
        # the tools' "never an exception" contract covers as_of too
        out = temporal_tools.get("policy-v1", as_of="not-a-date")
        assert out.startswith("Error:")
        assert "ISO-8601" in out

    def test_as_of_blank_is_ignored(self, temporal_tools: BundleTools) -> None:
        out = temporal_tools.get("policy-v1", as_of="  ")
        assert "superseded by `policy-v2`" in out
        assert "as of" not in out


class TestTraverseAsOf:
    """MCP ``traverse`` temporal replay (``as_of``).

    Parity with the ``okfsmith graph --as-of`` CLI flag (0.28.0) and the
    dashboard graph's ``?as_of=`` parameter (0.29.0): until now the MCP
    ``traverse`` tool hid superseded concepts, sorted by currency, and
    annotated temporal notes all at *now*, so an agent walking the graph
    at a past instant got the present's partitioning. Same bundle as
    ``TestSearchAsOf`` plus a ``hub`` concept linking to both policies.
    """

    @pytest.fixture()
    def temporal_tools(self, tmp_path: Path) -> BundleTools:
        bundle = Bundle(tmp_path)
        bundle.write_concept(
            "hub",
            {"title": "Policy Hub", "type": "policy"},
            "See [the old policy](policy-v1) and [the new policy](policy-v2).",
        )
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

    def test_default_traverse_hides_superseded(self, temporal_tools: BundleTools) -> None:
        out = temporal_tools.traverse("hub")
        assert "**policy-v2**" in out
        assert "**policy-v1**" not in out
        assert "1 superseded concept(s) hidden" in out

    def test_as_of_replays_past_state(self, temporal_tools: BundleTools) -> None:
        # Before policy-v2's valid_from, the old policy was the current one.
        out = temporal_tools.traverse("hub", as_of="2026-10-01")
        assert "**policy-v1**" in out
        assert "**policy-v2**" in out
        # current concepts sort before not-yet-valid ones
        assert out.index("**policy-v1**") < out.index("**policy-v2**")
        assert "superseded concept(s) hidden" not in out
        # the replay instant is labeled honestly, like the CLI envelope
        assert "Replayed as of 2026-10-01" in out

    def test_as_of_future_keeps_supersession(
        self, temporal_tools: BundleTools
    ) -> None:
        out = temporal_tools.traverse("hub", as_of="2027-01-01")
        assert "**policy-v2**" in out
        assert "**policy-v1**" not in out
        assert "1 superseded concept(s) hidden" in out

    def test_as_of_accepts_datetime(self, temporal_tools: BundleTools) -> None:
        out = temporal_tools.traverse("hub", as_of="2026-10-01T12:00:00Z")
        assert "**policy-v1**" in out

    def test_as_of_invalid_value_returns_error_not_exception(
        self, temporal_tools: BundleTools
    ) -> None:
        # the tools' "never an exception" contract covers as_of too
        out = temporal_tools.traverse("hub", as_of="not-a-date")
        assert out.startswith("Error:")
        assert "ISO-8601" in out

    def test_as_of_blank_is_ignored(self, temporal_tools: BundleTools) -> None:
        out = temporal_tools.traverse("hub", as_of="  ")
        assert "**policy-v2**" in out
        assert "**policy-v1**" not in out
        assert "Replayed as of" not in out


class TestNeighborsAsOf:
    """MCP ``neighbors`` temporal replay (``as_of``).

    Until now the MCP ``neighbors`` tool annotated nothing: an agent
    asking "which concepts does this policy link to?" got the present's
    answers on every row — a link to a superseded concept read exactly
    like a link to a current one, and there was no way to ask what the
    neighborhood looked like at a past instant. Same bundle as
    ``TestTraverseAsOf`` plus an ``old-note`` superseded by ``new-note``,
    so both directions (outgoing target, incoming source) can be
    superseded at now and current at the replay instant.
    """

    @pytest.fixture()
    def temporal_tools(self, tmp_path: Path) -> BundleTools:
        bundle = Bundle(tmp_path)
        bundle.write_concept(
            "hub",
            {"title": "Policy Hub", "type": "policy"},
            "See [the old policy](policy-v1) and [the new policy](policy-v2).",
        )
        bundle.write_concept(
            "policy-v1",
            {"title": "Refund Policy v1", "type": "policy"},
            "The old refund policy allows returns within 14 days of "
            "purchase. See [the hub](hub).",
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
        bundle.write_concept(
            "old-note",
            {"title": "Old Note", "type": "note"},
            "Background: see [the old policy](policy-v1).",
        )
        bundle.write_concept(
            "new-note",
            {
                "title": "New Note",
                "type": "note",
                "supersedes": ["old-note"],
                "valid_from": "2026-10-20",
            },
            "Background, updated.",
        )
        return BundleTools(bundle)

    @staticmethod
    def _row(out: str, concept_id: str, section: str) -> str:
        # Rows live under "## Outgoing (N)" / "## Incoming (N)"; the same
        # id can appear in both sections, so scope the lookup.
        head, _, rest = out.partition(f"## {section}")
        assert head != out or rest, f"section {section} missing"
        return next(
            line
            for line in rest.splitlines()
            if line.startswith(f"- **{concept_id}**")
        )

    def test_default_annotates_at_now(self, temporal_tools: BundleTools) -> None:
        out = temporal_tools.neighbors("hub")
        # Outgoing: the superseded target is flagged at now.
        assert "superseded by `policy-v2`" in self._row(out, "policy-v1", "Outgoing")
        assert "superseded" not in self._row(out, "policy-v2", "Outgoing")
        assert "not yet valid" not in self._row(out, "policy-v2", "Outgoing")
        # The current center concept carries no note; no replay label.
        assert "Note:" not in out
        assert "Replayed as of" not in out
        # Incoming: the superseded source is flagged too.
        out2 = temporal_tools.neighbors("policy-v1")
        assert "Note: **policy-v1** is superseded by `policy-v2`." in out2
        assert "superseded by `new-note`" in self._row(out2, "old-note", "Incoming")
        assert "superseded" not in self._row(out2, "hub", "Incoming")

    def test_as_of_replays_past_state(self, temporal_tools: BundleTools) -> None:
        # Before policy-v2's valid_from, the old policy was the current one.
        out = temporal_tools.neighbors("hub", as_of="2026-10-01")
        assert "superseded" not in self._row(out, "policy-v1", "Outgoing")
        assert "not yet valid" in self._row(out, "policy-v2", "Outgoing")
        # the replay instant is labeled honestly, like the CLI envelope
        assert "Replayed as of 2026-10-01" in out
        # The center concept and the incoming source replay too.
        out2 = temporal_tools.neighbors("policy-v1", as_of="2026-10-01")
        assert "Note:" not in out2
        assert "superseded" not in self._row(out2, "old-note", "Incoming")
        assert "Replayed as of 2026-10-01" in out2

    def test_as_of_future_keeps_supersession(
        self, temporal_tools: BundleTools
    ) -> None:
        out = temporal_tools.neighbors("hub", as_of="2027-01-01")
        assert "superseded by `policy-v2`" in self._row(out, "policy-v1", "Outgoing")
        assert "superseded" not in self._row(out, "policy-v2", "Outgoing")
        assert "Replayed as of 2027-01-01" in out
        out2 = temporal_tools.neighbors("policy-v1", as_of="2027-01-01")
        assert "superseded by `new-note`" in self._row(out2, "old-note", "Incoming")

    def test_as_of_accepts_datetime(self, temporal_tools: BundleTools) -> None:
        out = temporal_tools.neighbors("hub", as_of="2026-10-01T12:00:00Z")
        assert "superseded" not in self._row(out, "policy-v1", "Outgoing")
        assert "not yet valid" in self._row(out, "policy-v2", "Outgoing")
        assert "Replayed as of 2026-10-01" in out

    def test_as_of_invalid_value_returns_error_not_exception(
        self, temporal_tools: BundleTools
    ) -> None:
        # the tools' "never an exception" contract covers as_of too
        out = temporal_tools.neighbors("hub", as_of="not-a-date")
        assert out.startswith("Error:")
        assert "ISO-8601" in out

    def test_as_of_blank_is_ignored(self, temporal_tools: BundleTools) -> None:
        out = temporal_tools.neighbors("hub", as_of="  ")
        assert "superseded by `policy-v2`" in self._row(out, "policy-v1", "Outgoing")
        assert "Replayed as of" not in out


class TestProvenanceAsOf:
    """MCP ``provenance`` temporal replay (``as_of``).

    The concept's temporal status line was evaluated at *now* even when
    the caller wanted a past instant's answer. Same bundle as
    ``TestSearchAsOf``: ``policy-v1`` superseded by ``policy-v2``, whose
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

    def test_default_shows_temporal_status_at_now(
        self, temporal_tools: BundleTools
    ) -> None:
        out = temporal_tools.provenance("policy-v1")
        assert "Temporal status: superseded by `policy-v2`" in out
        assert "Replayed as of" not in out

    def test_as_of_replays_past_state(self, temporal_tools: BundleTools) -> None:
        # Before policy-v2's valid_from, the old policy was current.
        out = temporal_tools.provenance("policy-v1", as_of="2026-10-01")
        assert "superseded" not in out
        assert "Replayed as of 2026-10-01" in out
        # The not-yet-valid successor is flagged at the replay instant.
        out2 = temporal_tools.provenance("policy-v2", as_of="2026-10-01")
        assert "Temporal status: not yet valid" in out2
        assert "Replayed as of 2026-10-01" in out2

    def test_as_of_future_keeps_supersession(
        self, temporal_tools: BundleTools
    ) -> None:
        out = temporal_tools.provenance("policy-v1", as_of="2027-01-01")
        assert "Temporal status: superseded by `policy-v2`" in out
        assert "Replayed as of 2027-01-01" in out

    def test_as_of_accepts_datetime(self, temporal_tools: BundleTools) -> None:
        out = temporal_tools.provenance("policy-v1", as_of="2026-10-01T12:00:00Z")
        assert "superseded" not in out
        assert "Replayed as of 2026-10-01" in out

    def test_as_of_invalid_value_returns_error_not_exception(
        self, temporal_tools: BundleTools
    ) -> None:
        # the tools' "never an exception" contract covers as_of too
        out = temporal_tools.provenance("policy-v1", as_of="not-a-date")
        assert out.startswith("Error:")
        assert "ISO-8601" in out

    def test_as_of_blank_is_ignored(self, temporal_tools: BundleTools) -> None:
        out = temporal_tools.provenance("policy-v1", as_of="  ")
        assert "Temporal status: superseded by `policy-v2`" in out
        assert "Replayed as of" not in out


class TestValidate:
    """MCP ``validate`` tool (0.35.0).

    The MCP analogue of the ``okfsmith validate`` CLI command: until now
    an agent connected over MCP could read the bundle but could not check
    it — conformance and the advisory warnings were CLI-only. The tool
    runs the same ``okfsmith.validate.check`` the CLI runs, so the verdict
    never disagrees with the CLI's; ``strict`` mirrors ``--strict`` and
    ``as_of`` mirrors ``--as-of`` (0.32.0).
    """

    def test_conformant_bundle(self, tools: BundleTools) -> None:
        out = tools.validate()
        assert "Conformant: no errors, no warnings." in out
        assert "_4 concept(s) checked._" in out
        assert "## Errors (0)" in out
        assert "## Warnings (0)" in out
        assert "Validated as of" not in out

    @pytest.fixture()
    def stale_tools(self, tmp_path: Path) -> BundleTools:
        bundle = Bundle(tmp_path)
        bundle.write_concept(
            "policy-v2",
            {
                "title": "Refund Policy v2",
                "type": "policy",
                "stale_after": "2026-01-01T00:00:00+00:00",
            },
            "The new refund policy allows returns within 30 days of purchase.",
        )
        return BundleTools(bundle)

    def test_warnings_listed_and_strict_fails(self, stale_tools: BundleTools) -> None:
        out = stale_tools.validate()
        assert "Conformant with" in out
        assert "**W006**" in out
        assert "policy-v2.md" in out
        assert "content is stale" in out
        strict_out = stale_tools.validate(strict=True)
        assert "INVALID under --strict" in strict_out
        assert "**W006**" in strict_out

    def test_as_of_replays_w006_staleness(self, stale_tools: BundleTools) -> None:
        # At now (2026-11-21) the stale_after (2026-01-01) has passed.
        assert "**W006**" in stale_tools.validate()
        # Replayed to June 2025, before stale_after, the same memo is fresh.
        out = stale_tools.validate(as_of="2025-06-01")
        assert "**W006**" not in out
        assert "Validated as of 2025-06-01" in out

    def test_as_of_invalid_value_returns_error_not_exception(
        self, stale_tools: BundleTools
    ) -> None:
        # the tools' "never an exception" contract covers as_of too
        out = stale_tools.validate(as_of="not-a-date")
        assert out.startswith("Error:")
        assert "ISO-8601" in out

    def test_as_of_blank_is_ignored(self, stale_tools: BundleTools) -> None:
        out = stale_tools.validate(as_of="  ")
        assert "**W006**" in out
        assert "Validated as of" not in out

    @pytest.fixture()
    def broken_tools(self, tmp_path: Path) -> BundleTools:
        (tmp_path / "index.md").write_text("# Index\n", encoding="utf-8")
        (tmp_path / "bad.md").write_text(
            "No frontmatter here.\n", encoding="utf-8"
        )
        return BundleTools(Bundle.load(tmp_path))

    def test_errors_reported_as_invalid(self, broken_tools: BundleTools) -> None:
        out = broken_tools.validate()
        assert out.startswith("# Bundle validation")
        assert "INVALID: 1 error(s)" in out
        assert "**E001**" in out
        assert "`bad.md`" in out


class TestSearchListTemporalStatus:
    """MCP ``search`` hits and ``list`` rows show temporal status (0.25.0).

    The dashboard surfaces gained the same treatment in 0.21.0–0.24.0
    (detail, listing, search hits, graph), and ``traverse`` /
    ``provenance`` already append the note — but ``search`` and ``list``
    did not: a superseded concept revealed with
    ``include_superseded=True`` (or listed outright) read exactly like
    a current one, so an agent caller had no way to tell history from
    live knowledge. The note is evaluated at the replay instant when
    ``as_of`` is given, never at now.
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

    @staticmethod
    def _line(out: str, concept_id: str) -> str:
        # Match the row that *starts* with this id: a superseded row's
        # note names the superseding id, so a substring match would
        # return the wrong row.
        return next(
            line
            for line in out.splitlines()
            if line.startswith(f"- **{concept_id}**")
        )

    def test_search_marks_superseded_hit(self, temporal_tools: BundleTools) -> None:
        out = temporal_tools.search("refund", include_superseded=True)
        assert "superseded by `policy-v2`" in self._line(out, "policy-v1")
        assert "superseded" not in self._line(out, "policy-v2")

    def test_search_note_uses_replay_instant(
        self, temporal_tools: BundleTools
    ) -> None:
        # At 2026-10-01 v2 is not yet valid, so v1 is the current one:
        # the note follows the replay instant, not now.
        out = temporal_tools.search(
            "refund", as_of="2026-10-01", include_superseded=True
        )
        assert "superseded" not in self._line(out, "policy-v1")
        assert "not yet valid" in self._line(out, "policy-v2")

    def test_list_marks_superseded_row(self, temporal_tools: BundleTools) -> None:
        out = temporal_tools.list()
        assert "superseded by `policy-v2`" in self._line(out, "policy-v1")
        assert "superseded" not in self._line(out, "policy-v2")


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
