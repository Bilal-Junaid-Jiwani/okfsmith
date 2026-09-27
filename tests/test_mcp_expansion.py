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
    # write a sync-state manifest linking concept "a" to an ingested source;
    # the source lives inside the bundle root (manifest paths outside the
    # root are untrusted and never echoed — see the containment tests).
    state_dir = tmp_path / "kb" / ".okfsmith"
    state_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "kb" / "src1.md"
    src.write_text("source content", encoding="utf-8")
    digest = hashlib.sha256(b"source content").hexdigest()
    (state_dir / "sync-state.json").write_text(
        json.dumps(
            {
                "version": 1,
                "sources": {
                    "src1.md": {"sha256": digest, "concepts": ["a"], "size": 14}
                },
            }
        ),
        encoding="utf-8",
    )
    bundle = Bundle.load(tmp_path / "kb")  # reload so state is visible
    out = BundleTools(bundle).provenance("a")
    assert "# Provenance for a" in out
    # concept → sources[] entries
    assert "id: s1" in out and "Example Doc" in out
    assert "just-a-string-source" in out
    # ingested records: own section, shown once (not under every entry),
    # bundle-relative path only
    assert "## Ingested source records (1)" in out
    assert out.count("`src1.md`") == 1
    assert digest[:16] in out
    assert str(src) not in out  # absolute path never echoed verbatim
    # footnote refs → definitions
    assert "[^x]: The x definition" in out
    assert "[^missing]" in out and "definition not found" in out


def test_provenance_no_sync_state_no_crash(tmp_path: Path) -> None:
    out = BundleTools(_prov_bundle(tmp_path)).provenance("a")
    assert "No sync-state record links this concept" in out
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
    _write_bundle(
        tmp_path / "old",
        {
            "keep.md": _concept_doc("Keep", "same body\n"),
            "gone.md": _concept_doc("Gone", "will be removed\n"),
            "edit.md": _concept_doc("Edit", "original body\n"),
        },
    )
    _write_bundle(
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
    _write_bundle(
        kb,
        {
            "a.md": _concept_doc("Aye", "body a\n"),
            "b.md": _concept_doc("Bee", "body b\n"),
        },
    )
    # The recorded source lives inside the bundle root: manifest paths
    # outside the root are untrusted and never hashed (see the containment
    # tests), so the "changed" detection needs an in-bundle source.
    src_a = kb / "src_a.md"
    src_a.write_text("v1 content", encoding="utf-8")
    digest_v1 = hashlib.sha256(b"v1 content").hexdigest()
    state_dir = kb / ".okfsmith"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "sync-state.json").write_text(
        json.dumps(
            {
                "version": 1,
                "sources": {
                    "src_a.md": {
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
    # removed entries render id + an honest unavailable marker, not a bare id
    assert "- **vanished**\n" not in out
    assert "title/sha unavailable" in out
    assert "**a**" in out  # changed: source sha differs
    assert digest_v1[:12] in out and digest_v2[:12] in out
    # the in-bundle source path is echoed bundle-relative, never absolute
    assert "`src_a.md`" in out
    assert str(src_a) not in out


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


# ---------------------------------------------------------------------------
# reviewer-1 findings on the P6 expansion (10): regression tests
# ---------------------------------------------------------------------------
#
# The continuation-token paging used to build page 1 over
# ``notes + units`` but later pages over ``units`` only, so offsets
# overshot and items silently vanished whenever notes were present; notes
# and ``##`` section headers also consumed the ``max_chunks`` item budget
# and inflated the "N more" count.


def _page_item_ids(tools: BundleTools, method: str, *args, **kwargs) -> list[str]:
    """Concept ids (``- **id**`` rows) across every page with max_chunks=1."""
    ids: list[str] = []
    token: str | None = None
    for _ in range(50):
        out = getattr(tools, method)(
            *args, max_chunks=1, continuation_token=token, **kwargs
        )
        ids.extend(re.findall(r"^- \*\*([^*]+)\*\*", out, re.M))
        token = _continuation_token(out)
        if token is None:
            break
    else:
        pytest.fail("paging did not terminate")
    return ids


def _noted_bundle(tmp_path: Path) -> Bundle:
    """Bundle whose search/traverse results carry notes (hidden superseded)."""
    return _write_bundle(
        tmp_path / "kb",
        {
            "a.md": _concept_doc("Alpha", "the old alpha notes\n"),
            "b.md": _concept_doc("Beta", "more old beta notes\n"),
            "old.md": _concept_doc("Old", "old stuff here\n"),
            "new.md": _concept_doc(
                "New", "replacement\n", extra_fm="supersedes:\n  - old\n"
            ),
        },
    )


def test_paging_round_trip_with_notes_search(tmp_path: Path) -> None:
    """Reviewer gap 1: paged union == unpaged output when notes present."""
    tools = BundleTools(_noted_bundle(tmp_path))
    unpaged = tools.search("old")
    assert "superseded concept(s) hidden" in unpaged  # the note is present
    assert _page_item_ids(tools, "search", "old") == re.findall(
        r"^- \*\*([^*]+)\*\*", unpaged, re.M
    ) == ["a", "b"]


def test_paging_round_trip_with_notes_traverse(tmp_path: Path) -> None:
    """Reviewer gap 2: traverse paging with depth-cap + hidden notes."""
    bundle = _write_bundle(
        tmp_path / "kb",
        {
            "a.md": _concept_doc("A", "see [b](b), [c](c), [old](old)\n"),
            "b.md": _concept_doc("B", "x\n"),
            "c.md": _concept_doc("C", "y\n"),
            "old.md": _concept_doc("Old", "z\n"),
            "new.md": _concept_doc(
                "New", "w\n", extra_fm="supersedes:\n  - old\n"
            ),
        },
    )
    tools = BundleTools(bundle)
    unpaged = tools.traverse("a", depth=99)  # depth-cap note + hidden note
    assert "Depth capped at 3" in unpaged
    assert "superseded concept(s) hidden" in unpaged
    assert _page_item_ids(tools, "traverse", "a", depth=99) == re.findall(
        r"^- \*\*([^*]+)\*\*", unpaged, re.M
    ) == ["b", "c"]


def test_paging_round_trip_with_notes_diff(tmp_path: Path) -> None:
    """Reviewer gap 3: diff paging with the comparison note."""
    old_root, new_root = _diff_bundles(tmp_path)
    tools = BundleTools(Bundle.load(new_root))
    unpaged = tools.diff(against=str(old_root))
    assert "Comparing the current bundle against" in unpaged  # the note
    assert _page_item_ids(tools, "diff", against=str(old_root)) == re.findall(
        r"^- \*\*([^*]+)\*\*", unpaged, re.M
    )


def test_notes_do_not_consume_chunk_budget(tmp_path: Path) -> None:
    tools = BundleTools(_noted_bundle(tmp_path))
    out = tools.search("old", max_chunks=1)
    # the hit is on page 1 *with* the note — the note is outside the budget
    assert "- **a**" in out
    assert "superseded concept(s) hidden" in out
    # "N more" counts remaining *units*, not note lines
    assert "…[truncated, 1 more]" in out


def test_section_headers_do_not_consume_chunk_budget(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path / "kb",
        {
            "a.md": _concept_doc("A", "see [b](b) and [c](c)\n"),
            "b.md": _concept_doc("B", "x\n"),
            "c.md": _concept_doc("C", "y\n"),
        },
    )
    out = BundleTools(bundle).traverse("a", max_chunks=1)
    assert "## Depth 1 (2)" in out
    assert "- **b**" in out  # header did not eat the single budget slot
    assert "…[truncated, 1 more]" in out  # one unit remains, not "2 more"


def _write_sync_state(kb: Path, sources: dict) -> None:
    state_dir = kb / ".okfsmith"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "sync-state.json").write_text(
        json.dumps({"version": 1, "sources": sources}), encoding="utf-8"
    )


def test_sync_state_outside_paths_never_hashed_or_echoed(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    _write_bundle(kb, {"a.md": _concept_doc("Aye", "body a\n")})
    # an "outside" host file the crafted bundle wants hashed
    secret = tmp_path / "secret.md"
    secret.write_text("host secret", encoding="utf-8")
    real_digest = hashlib.sha256(b"host secret").hexdigest()
    _write_sync_state(
        kb, {str(secret): {"sha256": "0" * 64, "concepts": ["a"]}}
    )
    out = BundleTools(Bundle.load(kb)).diff()
    assert real_digest[:12] not in out  # no fresh host digest leaked
    assert str(secret) not in out  # absolute path never echoed verbatim
    assert "untrusted manifest" in out  # clean marker instead
    assert "## Changed (0)" in out


def test_sync_state_dotdot_escape_rejected(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    _write_bundle(kb, {"a.md": _concept_doc("Aye", "body a\n")})
    escape = tmp_path / "escape.md"
    escape.write_text("escape", encoding="utf-8")
    _write_sync_state(
        kb, {"../escape.md": {"sha256": "0" * 64, "concepts": ["a"]}}
    )
    out = BundleTools(Bundle.load(kb)).diff()
    assert str(escape) not in out
    assert "untrusted manifest" in out
    assert "## Changed (0)" in out


def test_sync_state_symlink_entry_rejected(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    _write_bundle(kb, {"a.md": _concept_doc("Aye", "body a\n")})
    target = tmp_path / "target.md"
    target.write_text("target", encoding="utf-8")
    (kb / "link.md").symlink_to(target)
    _write_sync_state(
        kb, {"link.md": {"sha256": "0" * 64, "concepts": ["a"]}}
    )
    out = BundleTools(Bundle.load(kb)).diff()
    assert "untrusted manifest" in out  # symlinked entries are never followed
    assert "## Changed (0)" in out


def test_provenance_trailing_dotdot_manifest_paths_not_echoed(
    tmp_path: Path,
) -> None:
    kb = tmp_path / "kb"
    _write_bundle(
        kb, {"a.md": "---\ntitle: A\nsources:\n  - id: s1\n---\n\nbody\n"}
    )
    (kb / "good.md").write_text("real source", encoding="utf-8")
    _write_sync_state(
        kb,
        {
            "sub/..": {"sha256": "d" * 64, "concepts": ["a"]},
            "sub/../..": {"sha256": "d" * 64, "concepts": ["a"]},
            "a.md/..": {"sha256": "d" * 64, "concepts": ["a"]},
            "..": {"sha256": "d" * 64, "concepts": ["a"]},
            "good.md": {"sha256": "d" * 64, "concepts": ["a"]},
        },
    )
    out = BundleTools(Bundle.load(kb)).provenance("a")
    # trailing-.. entries are untrusted, never echoed as ingested records
    assert "## Ingested source records (1)" in out
    assert "`good.md`" in out
    for bad in ("`sub/..`", "`a.md/..`", "`sub/../..`", "`..`"):
        assert bad not in out
    assert "untrusted manifest" in out


def test_manifest_relpath_trailing_dotdot_rejected(tmp_path: Path) -> None:
    from okfsmith.mcp_server.server import _manifest_relpath

    kb = tmp_path / "kb"
    _write_bundle(kb, {"a.md": _concept_doc("Aye", "body a\n")})
    bundle = Bundle.load(kb)
    for raw in ("sub/..", "sub/../..", "a.md/..", "..", "./sub/..", "sub//.."):
        assert _manifest_relpath(bundle, raw) is None, raw
    # legit entries still resolve to bundle-relative paths
    assert _manifest_relpath(bundle, "a.md") == "a.md"
    assert _manifest_relpath(bundle, "sub/../a.md") == "a.md"


def test_provenance_outside_manifest_path_not_echoed(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    _write_bundle(
        kb, {"a.md": "---\ntitle: A\nsources:\n  - id: s1\n---\n\nbody\n"}
    )
    secret = tmp_path / "secret.md"
    secret.write_text("host secret", encoding="utf-8")
    _write_sync_state(
        kb, {str(secret): {"sha256": "f" * 64, "concepts": ["a"]}}
    )
    out = BundleTools(Bundle.load(kb)).provenance("a")
    assert str(secret) not in out
    assert "untrusted manifest" in out
    assert "## Ingested source records (0)" in out


def test_provenance_ingested_records_shown_once(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    _write_bundle(
        kb,
        {
            "a.md": (
                "---\ntitle: Alpha\nsources:\n  - id: s1\n  - id: s2\n---\n\nbody\n"
            ),
        },
    )
    (kb / "rec.md").write_text("x", encoding="utf-8")
    digest = hashlib.sha256(b"x").hexdigest()
    _write_sync_state(
        kb, {"rec.md": {"sha256": digest, "concepts": ["a"]}}
    )
    out = BundleTools(Bundle.load(kb)).provenance("a")
    assert "## Ingested source records (1)" in out
    assert out.count("`rec.md`") == 1  # once, not under every sources[] entry
    assert digest[:16] in out


def test_provenance_ingested_records_without_sources(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    _write_bundle(kb, {"b.md": "---\ntitle: Bee\n---\n\nbody b\n"})
    (kb / "rec.md").write_text("x", encoding="utf-8")
    _write_sync_state(
        kb, {"rec.md": {"sha256": hashlib.sha256(b"x").hexdigest(), "concepts": ["b"]}}
    )
    out = BundleTools(Bundle.load(kb)).provenance("b")
    # records are visible even though `sources[]` is absent
    assert "## Ingested source records (1)" in out
    assert "`rec.md`" in out


def test_diff_sync_state_removed_not_bare_id(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    _write_bundle(kb, {"a.md": _concept_doc("Aye", "body\n")})
    _write_sync_state(kb, {"s": {"sha256": "0" * 64, "concepts": ["gone"]}})
    out = BundleTools(Bundle.load(kb)).diff()
    assert "- **gone**\n" not in out
    assert "- **gone** — " in out  # consistent id + detail shape


def test_out_of_range_continuation_token_clean_error(tmp_path: Path) -> None:
    tools = BundleTools(_link_bundle(tmp_path))
    out = tools.list(continuation_token=_encode_continuation(999))
    assert out.startswith("Error:")
    assert "out of range" in out
    # offset == total is also past the end (tokens always point at an item)
    out2 = tools.list(continuation_token=_encode_continuation(3))
    assert out2.startswith("Error:")
    assert "out of range" in out2


def test_invalid_token_error_not_query_bound(tmp_path: Path) -> None:
    out = BundleTools(_link_bundle(tmp_path)).list(
        continuation_token="!!!not-base64!!!"
    )
    assert out.startswith("Error: invalid `continuation_token`")
    assert "from another query" not in out  # tokens are not query-bound
    assert "opaque paging cursor" in out


def test_max_tokens_zero_empty_with_marker(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path / "kb",
        {f"c{i}.md": _concept_doc(f"C{i}", "body\n") for i in range(3)},
    )
    out = BundleTools(bundle).list(max_tokens=0)
    assert out.startswith("# Concepts (3)")
    assert "- **c0**" not in out  # no content output
    assert "…[truncated, 3 more]" in out  # ...with the marker
    assert "continuation_token" not in out  # no token that could not progress


def test_max_tokens_negative_is_unbounded(tmp_path: Path) -> None:
    tools = BundleTools(_link_bundle(tmp_path))
    assert tools.list(max_tokens=-5) == tools.list()
    assert tools.list(max_tokens="bogus") == tools.list()


def test_diff_against_too_many_files_clean_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from okfsmith.mcp_server import server as _server

    monkeypatch.setattr(_server, "_DIFF_AGAINST_MAX_FILES", 2)
    big = tmp_path / "big"
    for i in range(3):
        (big / f"c{i}.md").parent.mkdir(parents=True, exist_ok=True)
        (big / f"c{i}.md").write_text("x\n", encoding="utf-8")
    tools = BundleTools(_link_bundle(tmp_path))
    out = tools.diff(against=str(big))
    assert out.startswith("Error:")
    assert "too many" in out


def test_diff_against_empty_dir_clean_error(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    out = BundleTools(_link_bundle(tmp_path)).diff(against=str(empty))
    assert out.startswith("Error:")
    assert "bundle directory" in out
