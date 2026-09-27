"""Tests for the P6 MCP server expansion: traverse / provenance / diff tools
and evidence budgets (max_chunks, max_tokens, continuation_token).

The underlying tool functions (``BundleTools`` methods) are called directly —
no live MCP transport is needed. Requires the ``mcp`` extra (fastmcp) for the
tool-registration test; everything else only needs the server module.

Requires the ``mcp`` extra (fastmcp). If it is not installed, everything is
skipped with a clear reason.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
from pathlib import Path

import pytest

fastmcp = pytest.importorskip("fastmcp", reason="mcp extra not installed")

from okfsmith.core import Bundle  # noqa: E402
from okfsmith.core import frontmatter as _fm  # noqa: E402
from okfsmith.mcp_server.server import (  # noqa: E402
    BundleTools,
    _decode_continuation,
    _encode_continuation,
    build_server,
)

FIXTURE_BUNDLE = Path(__file__).resolve().parent.parent / ".contract" / "fixtures" / "valid"


def _write_bundle(root: Path, files: dict[str, str]) -> Bundle:
    """Write *files* (rel path → text) under *root* and load as a bundle."""
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return Bundle.load(root)


def _concept_doc(title: str, body: str, extra_fm: str = "") -> str:
    return f"---\ntitle: {title}\n{extra_fm}---\n\n{body}\n"


def _continuation_token(output: str) -> str | None:
    match = re.search(r'continuation_token="([^"]+)"', output)
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# traverse
# ---------------------------------------------------------------------------


def _link_bundle(tmp_path: Path) -> Bundle:
    return _write_bundle(
        tmp_path / "kb",
        {
            "index.md": "# Test index\n\n- [a](a)\n",
            "a.md": _concept_doc(
                "Alpha", "See [the bee](b) and [the cee](c).\n"
            ),
            "b.md": _concept_doc("Beta", "Links back to [alpha](a).\n"),
            "c.md": _concept_doc("Gamma", "Nothing here.\n"),
        },
    )


def test_traverse_depth_one(tmp_path: Path) -> None:
    tools = BundleTools(_link_bundle(tmp_path))
    out = tools.traverse("a", depth=1)
    assert "## Depth 1 (2)" in out
    assert "**b**" in out and "**c**" in out
    assert "## Depth 2" not in out


def test_traverse_depth_two_reaches_further(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path / "kb",
        {
            "a.md": _concept_doc("Alpha", "See [the bee](b).\n"),
            "b.md": _concept_doc("Beta", "See [the cee](c).\n"),
            "c.md": _concept_doc("Gamma", "The end.\n"),
        },
    )
    tools = BundleTools(bundle)
    out = tools.traverse("a", depth=2)
    assert "## Depth 1 (1)" in out
    assert "## Depth 2 (1)" in out
    assert "**c**" in out


def test_traverse_cycle_safe(tmp_path: Path) -> None:
    tools = BundleTools(_link_bundle(tmp_path))
    out = tools.traverse("a", depth=3)
    # b links back to a: the cycle must not loop, and each id appears once
    # as a traversed concept (depth 1: b, c — depth 2 finds nothing new).
    assert out.count("## Depth") == 1
    concept_lines = [ln for ln in out.splitlines() if ln.startswith("- **")]
    ids = [ln.split("**")[1] for ln in concept_lines]
    assert sorted(ids) == ["b", "c"]


def test_traverse_relation_filter_link_text(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path / "kb",
        {
            "a.md": _concept_doc(
                "Alpha",
                "See [computed by the engine](alpha) and [related reading](beta).\n",
            ),
            "alpha.md": _concept_doc("Alpha engine", "x\n"),
            "beta.md": _concept_doc("Beta notes", "y\n"),
        },
    )
    tools = BundleTools(bundle)
    out = tools.traverse("a", relation_filter="computed")
    assert "**alpha**" in out
    assert "**beta**" not in out
    # target-prefix matching (no explicit relation type in the link model)
    out2 = tools.traverse("a", relation_filter="bet")
    assert "**beta**" in out2
    assert "**alpha**" not in out2


def test_traverse_depth_capped(tmp_path: Path) -> None:
    tools = BundleTools(_link_bundle(tmp_path))
    out = tools.traverse("a", depth=99)
    assert "depth ≤ 3" in out
    assert "Depth capped at 3" in out


def test_traverse_missing_concept(tmp_path: Path) -> None:
    tools = BundleTools(_link_bundle(tmp_path))
    out = tools.traverse("nope/missing")
    assert out.startswith("Error: concept")
    assert "not found" in out


def test_traverse_hides_superseded_by_default(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path / "kb",
        {
            "a.md": _concept_doc("Alpha", "See [old](old) and [new](new).\n"),
            "old.md": _concept_doc("Old", "superseded content\n"),
            "new.md": _concept_doc(
                "New", "replacement content\n", extra_fm="supersedes:\n  - old\n"
            ),
        },
    )
    tools = BundleTools(bundle)
    out = tools.traverse("a")
    assert "**new**" in out
    assert "**old**" not in out
    # the hidden concept is reported honestly, not silently dropped
    assert "1 superseded concept(s) hidden" in out
    revealed = tools.traverse("a", include_superseded=True)
    assert "**old**" in revealed
    assert "superseded concept(s) hidden" not in revealed


def test_traverse_bad_inputs_never_raise(tmp_path: Path) -> None:
    tools = BundleTools(_link_bundle(tmp_path))
    assert isinstance(tools.traverse("a", depth="bogus"), str)
    assert isinstance(tools.traverse("a", depth=-5), str)
    assert isinstance(tools.traverse("a", relation_filter=123), str)
    assert isinstance(tools.traverse("a", max_chunks="lots"), str)
    assert isinstance(tools.traverse("a", continuation_token=12345), str)
    assert isinstance(tools.traverse(None), str)
    assert tools.traverse(None).startswith("Error: concept")


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------


def _prov_bundle(tmp_path: Path) -> Bundle:
    return _write_bundle(
        tmp_path / "kb",
        {
            "a.md": (
                "---\n"
                "title: Alpha\n"
                "sources:\n"
                "  - id: s1\n"
                "    resource: https://example.com/doc\n"
                "    title: Example Doc\n"
                "  - just-a-string-source\n"
                "---\n\n"
                "Body with a footnote.[^x] And a dangling one.[^missing]\n\n"
                "[^x]: The x definition\n"
            ),
        },
    )


def test_provenance_chain(tmp_path: Path) -> None:
    bundle = _prov_bundle(tmp_path)
    # write a sync-state manifest linking concept "a" to an ingested source
    state_dir = tmp_path / "kb" / ".okfsmith"
    state_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "src1.md"
    src.write_text("source content", encoding="utf-8")
    digest = hashlib.sha256(b"source content").hexdigest()
    (state_dir / "sync-state.json").write_text(
        json.dumps(
            {
                "version": 1,
                "sources": {
                    str(src): {"sha256": digest, "concepts": ["a"], "size": 14}
                },
            }
        ),
        encoding="utf-8",
    )
    bundle = Bundle.load(tmp_path / "kb")  # reload so state is visible
    out = BundleTools(bundle).provenance("a")
    assert "# Provenance for a" in out
    # concept → sources[] entry → source file/digest
    assert "id: s1" in out and "Example Doc" in out
    assert "just-a-string-source" in out
    assert str(src) in out
    assert digest[:16] in out
    # footnote refs → definitions
    assert "[^x]: The x definition" in out
    assert "[^missing]" in out and "definition not found" in out


def test_provenance_no_sync_state_no_crash(tmp_path: Path) -> None:
    out = BundleTools(_prov_bundle(tmp_path)).provenance("a")
    assert "no sync-state record" in out
    assert "[^x]: The x definition" in out


def test_provenance_malformed_sources_never_crash(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path / "kb",
        {
            "weird.md": "---\ntitle: Weird\nsources: 42\n---\nbody [^1]\n",
            "strsrc.md": "---\ntitle: S\nsources: just-a-url\n---\nplain\n",
            "nofm.md": "no frontmatter at all, [^a] ref\n",
        },
    )
    tools = BundleTools(bundle)
    for cid in ("weird", "strsrc", "nofm"):
        out = tools.provenance(cid)
        assert isinstance(out, str) and out
    assert "42" in tools.provenance("weird")
    assert "No `sources[]` entries" in tools.provenance("nofm")


def test_provenance_missing_concept(tmp_path: Path) -> None:
    out = BundleTools(_prov_bundle(tmp_path)).provenance("nope")
    assert out.startswith("Error: concept")
    assert "not found" in out


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


def _diff_bundles(tmp_path: Path) -> tuple[Path, Path]:
    old = _write_bundle(
        tmp_path / "old",
        {
            "keep.md": _concept_doc("Keep", "same body\n"),
            "gone.md": _concept_doc("Gone", "will be removed\n"),
            "edit.md": _concept_doc("Edit", "original body\n"),
        },
    )
    new = _write_bundle(
        tmp_path / "new",
        {
            "keep.md": _concept_doc("Keep", "same body\n"),
            "fresh.md": _concept_doc("Fresh", "brand new\n"),
            "edit.md": _concept_doc("Edit", "changed body\n"),
        },
    )
    return tmp_path / "old", tmp_path / "new"


def test_diff_against_dir(tmp_path: Path) -> None:
    old_root, new_root = _diff_bundles(tmp_path)
    tools = BundleTools(Bundle.load(new_root))
    out = tools.diff(against=str(old_root))
    assert "# Bundle diff" in out
    assert "## Added (1)" in out and "**fresh**" in out
    assert "## Removed (1)" in out and "**gone**" in out
    assert "## Changed (1)" in out and "**edit**" in out
    # changed entries show old → new body shas
    old_sha = hashlib.sha256(Bundle.load(old_root).get("edit").body.encode()).hexdigest()[:12]
    new_sha = hashlib.sha256(Bundle.load(new_root).get("edit").body.encode()).hexdigest()[:12]
    assert old_sha in out and new_sha in out
    assert "**keep**" not in out


def test_diff_no_changes(tmp_path: Path) -> None:
    old_root, _ = _diff_bundles(tmp_path)
    tools = BundleTools(Bundle.load(old_root))
    out = tools.diff(against=str(old_root))
    assert "## Added (0)" in out
    assert "## Removed (0)" in out
    assert "## Changed (0)" in out


def test_diff_bad_against_values(tmp_path: Path) -> None:
    tools = BundleTools(_link_bundle(tmp_path))
    assert tools.diff(against="/does/not/exist").startswith("Error:")
    assert "not a directory" in tools.diff(against="/does/not/exist")
    assert tools.diff(against="").startswith("Error:")
    assert tools.diff(against=123).startswith("Error:")
    # a file, not a directory
    some_file = tmp_path / "kb" / "a.md"
    assert "not a directory" in tools.diff(against=str(some_file))


def test_diff_no_against_no_state_clean_error(tmp_path: Path) -> None:
    out = BundleTools(_link_bundle(tmp_path)).diff()
    assert out.startswith("Error:")
    assert "sync-state.json" in out
    assert "against=" in out


def test_diff_against_sync_state(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    bundle = _write_bundle(
        kb,
        {
            "a.md": _concept_doc("Aye", "body a\n"),
            "b.md": _concept_doc("Bee", "body b\n"),
        },
    )
    src_a = tmp_path / "src_a.md"
    src_a.write_text("v1 content", encoding="utf-8")
    digest_v1 = hashlib.sha256(b"v1 content").hexdigest()
    state_dir = kb / ".okfsmith"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "sync-state.json").write_text(
        json.dumps(
            {
                "version": 1,
                "sources": {
                    str(src_a): {
                        "sha256": digest_v1,
                        "concepts": ["a", "vanished"],
                        "size": 10,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    # the recorded source file changed since the snapshot → "a" is changed
    src_a.write_text("v2 content", encoding="utf-8")
    digest_v2 = hashlib.sha256(b"v2 content").hexdigest()
    tools = BundleTools(Bundle.load(kb))
    out = tools.diff()
    assert "sync-state.json" in out
    assert "**b**" in out  # added: in bundle, not in snapshot
    assert "**vanished**" in out  # removed: in snapshot, not in bundle
    assert "**a**" in out  # changed: source sha differs
    assert digest_v1[:12] in out and digest_v2[:12] in out


def test_diff_corrupt_sync_state_clean_error(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    _write_bundle(kb, {"a.md": _concept_doc("Aye", "body\n")})
    state_dir = kb / ".okfsmith"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "sync-state.json").write_text("not json {{{", encoding="utf-8")
    out = BundleTools(Bundle.load(kb)).diff()
    assert out.startswith("Error:")
    assert "sync-state.json" in out


# ---------------------------------------------------------------------------
# evidence budgets: max_chunks / max_tokens / continuation_token
# ---------------------------------------------------------------------------


def test_search_budget_truncation_marker(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path / "kb",
        {f"c{i}.md": _concept_doc(f"C{i}", f"shared keyword body {i}\n") for i in range(5)},
    )
    tools = BundleTools(bundle)
    out = tools.search("shared keyword", max_chunks=2)
    assert out.count("**c") == 2
    assert "…[truncated, 3 more]" in out
    assert _continuation_token(out) is not None


def test_continuation_round_trip_collects_all(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path / "kb",
        {f"c{i}.md": _concept_doc(f"C{i}", f"body {i}\n") for i in range(5)},
    )
    tools = BundleTools(bundle)
    seen: list[str] = []
    token: str | None = None
    pages = 0
    while True:
        if token:
            out = tools.list(max_chunks=2, continuation_token=token)
        else:
            out = tools.list(max_chunks=2)
        pages += 1
        assert pages < 10, "paging did not terminate"
        seen.extend(re.findall(r"^- \*\*([^*]+)\*\*", out, re.M))
        token = _continuation_token(out)
        if token is None:
            break
    assert pages == 3
    assert sorted(seen) == [f"c{i}" for i in range(5)]
    # last page carries no token and no truncation marker
    assert "…[truncated" not in out


def test_continuation_token_opaque_round_trip() -> None:
    token = _encode_continuation(7)
    assert _decode_continuation(token) == 7
    assert _decode_continuation(_encode_continuation(0)) == 0


@pytest.mark.parametrize(
    "bad",
    [
        "!!!not-base64!!!",
        "eyJ2Ijo5LCJvIjowfQ",  # wrong payload version
        _encode_continuation(3)[:-2] + "xx",  # tampered
        12345,
        ["o", 1],
        "x" * 300,  # over-long
    ],
)
def test_invalid_continuation_token_clean_error(tmp_path: Path, bad) -> None:
    tools = BundleTools(_link_bundle(tmp_path))
    for tool_out in (
        tools.list(continuation_token=bad),
        tools.search("alpha", continuation_token=bad),
        tools.traverse("a", continuation_token=bad),
        tools.provenance("a", continuation_token=bad),
        tools.diff(against=str(tmp_path / "kb"), continuation_token=bad),
        tools.get("a", continuation_token=bad),
        tools.neighbors("a", continuation_token=bad),
        tools.index(continuation_token=bad),
    ):
        assert tool_out.startswith("Error: invalid `continuation_token`"), tool_out[:80]


def test_max_chunks_capped_at_fifty(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path / "kb",
        {f"c{i:02d}.md": _concept_doc(f"C{i:02d}", "body\n") for i in range(60)},
    )
    tools = BundleTools(bundle)
    out = tools.list(limit=60, max_chunks=9999)
    rows = [ln for ln in out.splitlines() if ln.startswith("- **")]
    assert len(rows) == 50  # hard cap, not 60 and not 9999
    assert "…[truncated, 10 more]" in out


def test_max_tokens_truncates_get(tmp_path: Path) -> None:
    long_body = "".join(f"line {i} of a long document body\n" for i in range(120))
    bundle = _write_bundle(
        tmp_path / "kb", {"long.md": _concept_doc("Long", long_body)}
    )
    tools = BundleTools(bundle)
    full = tools.get("long")
    out = tools.get("long", max_tokens=10)
    assert len(out) < len(full)
    assert "…[truncated," in out
    assert _continuation_token(out) is not None
    # paging through resumes the document
    resumed = tools.get("long", max_tokens=10, continuation_token=_continuation_token(out))
    assert "line 60" in resumed or "line 50" in resumed


def test_budgets_do_not_change_default_output(tmp_path: Path) -> None:
    """Default budget values must reproduce the legacy tool output exactly."""
    bundle = Bundle.load(FIXTURE_BUNDLE)
    tools = BundleTools(bundle)
    assert tools.get("finance/revenue") == _fm.serialize_frontmatter(
        bundle.get("finance/revenue").frontmatter,
        bundle.get("finance/revenue").body,
    )
    assert tools.index() == bundle.index_text


# ---------------------------------------------------------------------------
# backward compatibility: old tools' signatures and calling conventions
# ---------------------------------------------------------------------------


def test_old_signatures_unchanged() -> None:
    params = lambda fn: list(inspect.signature(fn).parameters)  # noqa: E731
    assert params(BundleTools.index)[:1] == ["self"]
    assert params(BundleTools.list)[1:3] == ["filter_type", "limit"]
    assert params(BundleTools.search)[1:3] == ["query", "limit"]
    assert params(BundleTools.get)[1:2] == ["concept_id"]
    assert params(BundleTools.neighbors)[1:2] == ["concept_id"]


def test_old_positional_calls_still_work() -> None:
    tools = BundleTools(Bundle.load(FIXTURE_BUNDLE))
    assert "finance/profit" in tools.list("Metric", 5)
    assert "finance/revenue" in tools.search("revenue", 3)
    assert "Customer Orders" in tools.get("finance/revenue")
    assert "## Outgoing" in tools.neighbors("finance/profit")
    assert "# OKF Test Bundle" in tools.index()


def test_search_output_unchanged_without_budgets() -> None:
    tools = BundleTools(Bundle.load(FIXTURE_BUNDLE))
    out = tools.search("revenue")
    assert "finance/revenue" in out and "computations/revenue" in out
    assert "…[truncated" not in out
    assert _continuation_token(out) is None


def test_build_server_registers_eight_tools() -> None:
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
    for tool in registered:
        assert tool.description and len(tool.description.split()) > 10, tool.name


# ---------------------------------------------------------------------------
# malformed input never crashes (C10) — across all eight tools
# ---------------------------------------------------------------------------


def test_malformed_bundle_all_tools_no_crash(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path / "kb",
        {
            # scalar tags / verified / sources, bad temporal values
            "a.md": (
                "---\ntitle: Alpha\ntags: 5\nverified: yes\nsources: 42\n"
                "supersedes: [also, fine]\nvalid_from: not-a-date\n---\n"
                "see [b mes](b) and [c](c) [^x]\n"
            ),
            "b.md": "---\ntitle: Beta\n---\nplain body\n",
            # invalid YAML block degrades to {} frontmatter, kept as body
            "c.md": "---\n: [unclosed\n---\nbody here\n",
        },
    )
    tools = BundleTools(bundle)
    assert "b" in tools.traverse("a")
    assert "42" in tools.provenance("a")
    assert "## Sources" in tools.provenance("c")
    assert "## Added" in tools.diff(against=str(tmp_path / "kb"))
    assert isinstance(tools.search("plain"), str)
    assert isinstance(tools.list(), str)
    assert isinstance(tools.get("a"), str)
    assert "Outgoing" in tools.neighbors("a")
    assert isinstance(tools.index(), str)
