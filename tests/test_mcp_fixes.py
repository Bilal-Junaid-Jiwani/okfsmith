"""Regression tests for the MCP-server QA findings fixed in this workstream.

- C10: scalar ``verified`` / ``tags`` in hand-written frontmatter must not
  crash ``list`` / ``search`` / ``neighbors`` — scalar tags coerce to a
  single-entry list, non-dict ``verified`` degrades per the spec's
  trust-tier rules (§5.3), never raising.
- Search upgrade: ``rank_concepts`` is a thin shim over the BM25 engine
  (``okfsmith.search.search_bundle``) with its back-compat signature.
- L15/L16: docstring–behavior alignment and graceful direct-call argument
  validation (clean errors, no tracebacks on bad input).
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from okfsmith.core import Bundle
from okfsmith.core.spec import trust_tier
from okfsmith.mcp_server.server import (
    BundleTools,
    _coerce_tags,
    _trust_tier_safe,
    rank_concepts,
)

FIXTURE_BUNDLE = Path(__file__).resolve().parent.parent / ".contract" / "fixtures" / "valid"


def _make_bundle(tmp_path: Path, docs: dict[str, str]) -> Bundle:
    """Write *docs* ({filename: text}) into *tmp_path* and load a Bundle."""
    for name, text in docs.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return Bundle.load(tmp_path)


@pytest.fixture()
def fixture_tools() -> BundleTools:
    assert FIXTURE_BUNDLE.is_dir(), f"fixture bundle missing: {FIXTURE_BUNDLE}"
    return BundleTools(Bundle.load(FIXTURE_BUNDLE))


# ---------------------------------------------------------------------------
# C10 — scalar `verified` must not crash list/search/neighbors
# ---------------------------------------------------------------------------


def test_scalar_verified_bool_no_crash(tmp_path: Path) -> None:
    bundle = _make_bundle(
        tmp_path,
        {"c.md": "---\ntitle: T\nverified: yes\n---\nbody about widgets\n"},
    )
    tools = BundleTools(bundle)
    assert "c" in tools.list()  # was: TypeError: 'bool' object is not iterable
    assert "c" in tools.search("widgets")
    assert "Outgoing" in tools.neighbors("c")
    assert "title: T" in tools.get("c")


def test_scalar_verified_bool_tier_matches_spec(tmp_path: Path) -> None:
    # QA L6: `_trust_tier_safe` delegates to the canonical
    # `spec.trust_tier`, so MCP tools and the CLI agree. A scalar
    # `verified: yes` names no actor, so there is no basis for a trust
    # tier → `unverified`.
    bundle = _make_bundle(tmp_path, {"c.md": "---\ntitle: T\nverified: yes\n---\nbody\n"})
    assert "*unverified*" in BundleTools(bundle).list()


def test_scalar_verified_int_and_str_degrade_safely(tmp_path: Path) -> None:
    for value in ("5", "bob", "true"):
        bundle = _make_bundle(
            tmp_path / f"v{value}", {"c.md": f"---\ntitle: T\nverified: {value}\n---\nbody\n"}
        )
        tools = BundleTools(bundle)
        out = tools.list()
        assert "*unverified*" in out
        assert "c" in tools.search("body")  # search also renders labels


def test_falsy_scalar_verified_is_unverified(tmp_path: Path) -> None:
    for i, value in enumerate(("no", "~", '""')):
        bundle = _make_bundle(
            tmp_path / f"case{i}",
            {"c.md": f"---\ntitle: T\nverified: {value}\n---\nbody\n"},
        )
        assert "*unverified*" in BundleTools(bundle).list()


def test_verified_mapping_still_human_reviewed(tmp_path: Path) -> None:
    bundle = _make_bundle(
        tmp_path,
        {"c.md": "---\ntitle: T\nverified:\n  - by: human:alice\n---\nbody\n"},
    )
    assert "*human-reviewed*" in BundleTools(bundle).list()


def test_trust_tier_safe_direct_cases() -> None:
    # QA L6: scalar `verified` now matches `spec.trust_tier` (unverified —
    # no actor info means no basis for a trust tier).
    assert _trust_tier_safe({"verified": True}) == "unverified"
    assert _trust_tier_safe({"verified": 5}) == "unverified"
    assert _trust_tier_safe({"verified": "bob"}) == "unverified"
    assert _trust_tier_safe({"verified": False}) == "unverified"
    assert _trust_tier_safe({"verified": None}) == "unverified"
    assert _trust_tier_safe({"verified": []}) == "unverified"
    assert _trust_tier_safe({}) == "unverified"
    assert _trust_tier_safe("not-a-dict") == "unverified"
    assert _trust_tier_safe({"verified": [{"by": "human:alice"}]}) == "human-reviewed"
    assert _trust_tier_safe({"verified": [{"by": "process:nightly"}]}) == "machine-confirmed"


def test_trust_tier_safe_agrees_with_spec() -> None:
    # The canonical spec function is the authority; the MCP helper must
    # never disagree with it on mapping frontmatter (QA L6).
    cases = [
        {},
        {"verified": True},
        {"verified": "yes"},
        {"verified": None},
        {"verified": []},
        {"verified": [{"by": "human:alice"}]},
        {"verified": [{"by": "process:nightly"}]},
        {"verified": {"by": "human:bob"}},
    ]
    for fm in cases:
        assert _trust_tier_safe(fm) == trust_tier(fm)


# ---------------------------------------------------------------------------
# C10 — scalar `tags` must not crash search (and coerces to a list)
# ---------------------------------------------------------------------------


def test_scalar_tags_int_no_crash(tmp_path: Path) -> None:
    bundle = _make_bundle(
        tmp_path, {"c.md": "---\ntitle: T\ntags: 5\n---\nbody about widgets\n"}
    )
    tools = BundleTools(bundle)
    assert "c" in tools.search("widgets")  # was: TypeError: 'int' not iterable
    assert "c" in tools.list()
    assert "Outgoing" in tools.neighbors("c")


def test_scalar_tags_str_becomes_single_entry_list(tmp_path: Path) -> None:
    bundle = _make_bundle(
        tmp_path, {"c.md": "---\ntitle: T\ntags: solo\n---\nplain body\n"}
    )
    assert "c" in BundleTools(bundle).search("solo")


def test_coerce_tags_shapes() -> None:
    assert _coerce_tags({}) == []
    assert _coerce_tags({"tags": None}) == []
    assert _coerce_tags({"tags": "solo"}) == ["solo"]
    assert _coerce_tags({"tags": ["a", "b"]}) == ["a", "b"]
    assert _coerce_tags({"tags": 5}) == ["5"]
    assert _coerce_tags({"tags": True}) == ["True"]


def test_mixed_malformed_bundle_stays_usable(tmp_path: Path) -> None:
    bundle = _make_bundle(
        tmp_path,
        {
            "a.md": "---\ntitle: Alpha\nverified: yes\ntags: 7\n---\nwidgets everywhere\n",
            "b.md": "---\ntitle: Beta\ntype: Metric\n---\nplain body text\n",
            "sub/c.md": "---\ntitle: Gamma\nverified:\n  - by: human:zoe\n---\nmore widgets\n",
        },
    )
    tools = BundleTools(bundle)
    listed = tools.list()
    for cid in ("a", "b", "sub/c"):
        assert cid in listed
    # scalar `verified: yes` is unverified per the canonical spec rule
    # (QA L6); nothing raised on the malformed input
    assert "*unverified*" in listed
    assert "*human-reviewed*" in listed
    searched = tools.search("widgets")
    assert "a" in searched and "sub/c" in searched
    assert "Incoming" in tools.neighbors("a")


# ---------------------------------------------------------------------------
# Search upgrade — rank_concepts as a thin shim
# ---------------------------------------------------------------------------


def test_rank_concepts_backcompat_signature() -> None:
    sig = inspect.signature(rank_concepts)
    params = list(sig.parameters)
    assert params == ["bundle", "query", "limit"]
    assert sig.parameters["limit"].default == 10


def test_rank_concepts_empty_query_returns_empty(fixture_tools: BundleTools) -> None:
    bundle = fixture_tools.bundle
    assert rank_concepts(bundle, "") == []
    assert rank_concepts(bundle, "   ") == []
    assert rank_concepts(bundle, None) == []


def test_rank_concepts_scores_descending(fixture_tools: BundleTools) -> None:
    ranked = rank_concepts(fixture_tools.bundle, "revenue")
    assert ranked, "expected hits for 'revenue'"
    scores = [score for score, _ in ranked]
    assert scores == sorted(scores, reverse=True)
    ids = [concept.id for _, concept in ranked]
    assert "finance/revenue" in ids
    assert "computations/revenue" in ids


def test_rank_concepts_limit_respected(fixture_tools: BundleTools) -> None:
    ranked = rank_concepts(fixture_tools.bundle, "revenue", limit=1)
    assert len(ranked) == 1
    assert rank_concepts(fixture_tools.bundle, "revenue", limit=-2) == []


def test_rank_concepts_docstring_notes_bm25_upgrade() -> None:
    doc = rank_concepts.__doc__ or ""
    assert "BM25" in doc
    assert "search_bundle" in doc
    assert "back-compat" in doc


def test_search_uses_ranked_engine(fixture_tools: BundleTools) -> None:
    # MCP search ordering matches rank_concepts ordering exactly.
    ranked_ids = [c.id for _, c in rank_concepts(fixture_tools.bundle, "revenue")]
    out = fixture_tools.search("revenue")
    out_ids = [
        line.split("**")[1]
        for line in out.splitlines()
        if line.startswith("- **")
    ]
    assert out_ids == ranked_ids[:10]


def test_search_ranking_prefers_title_matches(fixture_tools: BundleTools) -> None:
    out = fixture_tools.search("freshness")
    assert "incidents/playbook" in out
    first_hit = [line for line in out.splitlines() if line.startswith("- ")][0]
    assert "incidents/playbook" in first_hit


# ---------------------------------------------------------------------------
# L15/L16 — docstring alignment + graceful arg validation
# ---------------------------------------------------------------------------


def test_search_docstring_describes_bm25_not_substring() -> None:
    doc = BundleTools.search.__doc__ or ""
    assert "BM25" in doc
    assert "substring" not in doc.lower()
    # tier ordering claim still matches the tier helper's output
    assert "human-reviewed" in doc and "unverified" in doc


def test_all_tool_docstrings_present_and_substantive() -> None:
    for name in ("index", "list", "search", "get", "neighbors"):
        doc = getattr(BundleTools, name).__doc__ or ""
        assert len(doc.split()) > 10, name


def test_search_none_query_returns_clean_error(fixture_tools: BundleTools) -> None:
    out = fixture_tools.search(None)  # was: AttributeError: 'NoneType'
    assert out.startswith("Error:")
    assert "query" in out.lower()


def test_search_blank_and_non_str_query_no_traceback(
    fixture_tools: BundleTools,
) -> None:
    for bad in ("", "   ", 123, ["x"]):
        out = fixture_tools.search(bad)
        assert isinstance(out, str) and out.startswith("Error:"), bad


def test_search_bad_limit_no_traceback(fixture_tools: BundleTools) -> None:
    out = fixture_tools.search("revenue", limit="bogus")
    assert "finance/revenue" in out
    out = fixture_tools.search("revenue", limit=None)
    assert "finance/revenue" in out
    out = fixture_tools.search("revenue", limit=2.9)
    assert "finance/revenue" in out
    # negative limit → zero rows, still a clean message, never a traceback
    out = fixture_tools.search("revenue", limit=-3)
    assert isinstance(out, str)


def test_list_bad_limit_no_traceback(fixture_tools: BundleTools) -> None:
    out = fixture_tools.list(limit="bogus")
    assert "finance/revenue" in out
    assert "No concepts found" in fixture_tools.list(limit=-5)


def test_get_none_id_returns_clean_error(fixture_tools: BundleTools) -> None:
    out = fixture_tools.get(None)
    assert out.startswith("Error: concept")


def test_neighbors_none_id_returns_clean_error(fixture_tools: BundleTools) -> None:
    out = fixture_tools.neighbors(None)
    assert out.startswith("Error: concept")


# --- L17: build_server path validation (direct API) ---


def test_build_server_empty_path_rejected() -> None:
    from okfsmith.mcp_server.server import build_server

    with pytest.raises(ValueError, match="must not be empty"):
        build_server("")


def test_build_server_blank_path_rejected() -> None:
    from okfsmith.mcp_server.server import build_server

    with pytest.raises(ValueError, match="must not be empty"):
        build_server("   ")


def test_build_server_file_path_rejected(tmp_path: Path) -> None:
    from okfsmith.mcp_server.server import build_server

    target = tmp_path / "not-a-dir.md"
    target.write_text("# hi\n", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        build_server(target)
