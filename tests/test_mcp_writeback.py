"""Tests for the okfsmith MCP governed write-back tools.

The underlying tool functions (``BundleTools`` methods) are called directly —
no live MCP transport is needed. ``build_server`` registration of the four
new tools is asserted in ``tests/test_mcp.py``.

Requires the ``mcp`` extra (fastmcp). If it is not installed, everything is
skipped with a clear reason.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

fastmcp = pytest.importorskip("fastmcp", reason="mcp extra not installed")

import okfsmith.mcp_server.server as srv  # noqa: E402
from okfsmith.core import Bundle  # noqa: E402
from okfsmith.core import frontmatter as _fm  # noqa: E402
from okfsmith.core.spec import HUMAN_REVIEWED, UNVERIFIED, trust_tier  # noqa: E402
from okfsmith.mcp_server.server import BundleTools  # noqa: E402


def _write_bundle(root: Path, files: dict[str, str]) -> Bundle:
    """Write *files* (rel path → text) under *root* and load as a bundle."""
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return Bundle.load(root)


def _concept_doc(title: str, body: str, extra_fm: str = "") -> str:
    return f"---\ntitle: {title}\ntype: Note\n{extra_fm}---\n\n{body}\n"


def _reviewed_doc() -> str:
    return _concept_doc(
        "Reviewed",
        "Carefully reviewed body.",
        "verified:\n- by: human:alice\n  at: '2026-01-01T00:00:00+00:00'\n",
    )


def _snapshot(root: Path) -> dict[str, bytes]:
    """Map of rel path → bytes for every file under *root*."""
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and not p.is_symlink()
    }


def _parse(path: Path) -> tuple[dict, str]:
    return _fm.parse_frontmatter(path.read_text(encoding="utf-8"))


def _audit_entries(root: Path) -> list[dict]:
    audit = root / ".okfsmith" / "audit.jsonl"
    if not audit.is_file():
        return []
    return [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# preview_write_concept
# ---------------------------------------------------------------------------


def test_preview_is_side_effect_free(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    tools = BundleTools(_write_bundle(root, {"alpha.md": _concept_doc("Alpha", "Body.")}))
    before = _snapshot(root)
    out = tools.preview_write_concept(
        "My Note", "Body text.", sources=["https://example.com"], links=["alpha"]
    )
    assert _snapshot(root) == before
    assert not (root / ".okfsmith").exists()
    assert "`my-note`" in out
    assert "`my-note.md`" in out
    assert "unverified" in out
    assert "action: created" in out
    assert "actor: mcp:write_concept" in out
    assert "https://example.com" in out
    assert "Body text." in out
    assert "## Links" in out


def test_preview_reports_collision(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    tools = BundleTools(_write_bundle(root, {"alpha.md": _concept_doc("Alpha", "Body.")}))
    out = tools.preview_write_concept("Alpha", "Other body.")
    assert "Collision:" in out
    assert "update_concept" in out


def test_preview_rejects_empty_title_and_body(tmp_path: Path) -> None:
    tools = BundleTools(Bundle.load(tmp_path / "kb"))
    assert tools.preview_write_concept("  ", "body").startswith("Error:")
    assert tools.preview_write_concept("Title", "   ").startswith("Error:")


def test_preview_rejects_reserved_filename(tmp_path: Path) -> None:
    tools = BundleTools(Bundle.load(tmp_path / "kb"))
    out = tools.preview_write_concept("Index", "body")
    assert out.startswith("Error:")
    assert "reserved" in out


# ---------------------------------------------------------------------------
# write_concept
# ---------------------------------------------------------------------------


def test_write_concept_records_provenance_and_unverified(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    tools = BundleTools(Bundle.load(root))
    out = tools.write_concept("My Note", "Body text here.", sources=["https://example.com"])
    assert "Concept written" in out
    assert "`my-note`" in out
    fm, body = _parse(root / "my-note.md")
    assert fm["type"] == "Note"
    assert fm["title"] == "My Note"
    assert "verified" not in fm
    assert trust_tier(fm) == UNVERIFIED
    assert fm["generated"]["by"] == "mcp:write_concept"
    assert fm["sources"] == ["https://example.com"]
    prov = fm["provenance"]
    assert len(prov) == 1
    entry = prov[0]
    assert entry["action"] == "created"
    assert entry["actor"] == "mcp:write_concept"
    assert entry["sources"] == ["https://example.com"]
    assert entry["at"].endswith("+00:00")
    assert "Body text here." in body
    assert "Body text here." in tools.get("my-note")


def test_write_concept_strips_verified_markers(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    tools = BundleTools(Bundle.load(root))
    tools.write_concept(
        "Sneaky",
        "Body.",
        sources=[{"title": "Evil source", "verified": [{"by": "human:mallory"}]}],
    )
    fm, _ = _parse(root / "sneaky.md")
    assert "verified" not in fm
    assert trust_tier(fm) == UNVERIFIED
    assert fm["sources"] == [{"title": "Evil source"}]


def test_write_concept_collision_returns_error_not_overwrite(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    tools = BundleTools(Bundle.load(root))
    tools.write_concept("Alpha", "First body.")
    first = (root / "alpha.md").read_bytes()
    out = tools.write_concept("Alpha", "Second body.")
    assert out.startswith("Error:")
    assert "already exists" in out
    assert "update_concept" in out
    assert (root / "alpha.md").read_bytes() == first
    assert len(_audit_entries(root)) == 1


def test_write_concept_rejects_empty_inputs(tmp_path: Path) -> None:
    tools = BundleTools(Bundle.load(tmp_path / "kb"))
    assert tools.write_concept("  ", "body").startswith("Error:")
    assert tools.write_concept("Title", "").startswith("Error:")


def test_write_concept_traversal_title_stays_in_bundle(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    tools = BundleTools(Bundle.load(root))
    out = tools.write_concept("../../evil", "Body text.")
    assert "Concept written" in out
    assert (root / "untitled" / "untitled" / "evil.md").is_file()
    assert not (tmp_path / "evil.md").exists()
    assert not (tmp_path / "untitled").exists()


def test_write_concept_with_links_section(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    tools = BundleTools(Bundle.load(root))
    tools.write_concept("Linked", "Body.", links=["a/b", {"text": "See C", "target": "c/d"}])
    text = (root / "linked.md").read_text(encoding="utf-8")
    assert "- [a/b](a/b)" in text
    assert "- [See C](c/d)" in text
    assert "<!-- okfsmith:mcp:links -->" in text


# ---------------------------------------------------------------------------
# update_concept
# ---------------------------------------------------------------------------


def test_update_refuses_human_reviewed_without_downgrade(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    doc = _reviewed_doc()
    tools = BundleTools(_write_bundle(root, {"reviewed.md": doc}))
    out = tools.update_concept("reviewed", body="Agent rewrite.")
    assert out.startswith("Error:")
    assert "human-reviewed" in out
    assert "downgrade_trust" in out
    assert (root / "reviewed.md").read_text(encoding="utf-8") == doc
    assert _audit_entries(root) == []


def test_update_downgrade_trust_removes_verified_and_records(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    tools = BundleTools(_write_bundle(root, {"reviewed.md": _reviewed_doc()}))
    out = tools.update_concept("reviewed", body="Agent rewrite.", downgrade_trust=True)
    assert "Concept updated" in out
    fm, body = _parse(root / "reviewed.md")
    assert "verified" not in fm
    assert trust_tier(fm) == UNVERIFIED
    assert "Agent rewrite." in body
    entry = fm["provenance"][-1]
    assert entry["action"] == "updated"
    assert entry["actor"] == "mcp:update_concept"
    assert entry["downgrade_trust"] is True
    assert entry["previous_trust"] == HUMAN_REVIEWED
    assert entry["removed_verified_by"] == ["human:alice"]
    assert "Downgrade:" in out
def test_update_appends_provenance_history(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    tools = BundleTools(Bundle.load(root))
    tools.write_concept("Alpha", "Body one.")
    tools.update_concept("alpha", body="Body two.")
    tools.update_concept("alpha", title="Alpha Renamed")
    fm, _ = _parse(root / "alpha.md")
    prov = fm["provenance"]
    assert [e["action"] for e in prov] == ["created", "updated", "updated"]
    assert prov[0]["actor"] == "mcp:write_concept"
    assert prov[1]["fields"] == ["body"]
    assert prov[2]["fields"] == ["title"]


def test_update_dry_run_returns_diff_without_writing(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    tools = BundleTools(Bundle.load(root))
    tools.write_concept("Alpha", "Body one.")
    before = _snapshot(root)
    out = tools.update_concept("alpha", body="Body two.", dry_run=True)
    assert "dry run" in out
    assert "```diff" in out
    assert "-Body one." in out
    assert "+Body two." in out
    assert _snapshot(root) == before
    assert len(_audit_entries(root)) == 1


def test_update_noop_writes_nothing(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    tools = BundleTools(Bundle.load(root))
    tools.write_concept("Alpha", "Body.")
    before = _snapshot(root)
    out = tools.update_concept("alpha", body="Body.")
    assert "No changes" in out
    assert _snapshot(root) == before
    assert len(_audit_entries(root)) == 1


def test_update_replaces_links_section_without_stacking(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    tools = BundleTools(Bundle.load(root))
    tools.write_concept("Alpha", "Body.", links=["a/b"])
    tools.update_concept("alpha", links=["c/d"])
    text = (root / "alpha.md").read_text(encoding="utf-8")
    assert text.count("## Links") == 1
    assert text.count("okfsmith:mcp:links") == 1
    assert "c/d" in text
    assert "a/b" not in text


def test_update_missing_concept_returns_clean_error(tmp_path: Path) -> None:
    tools = BundleTools(Bundle.load(tmp_path / "kb"))
    out = tools.update_concept("does/not-exist", body="x")
    assert out.startswith("Error:")
    assert "not found" in out


def test_update_rejects_traversal_ids(tmp_path: Path) -> None:
    tools = BundleTools(Bundle.load(tmp_path / "kb"))
    out = tools.update_concept("../../etc/passwd", body="x")
    assert out.startswith("Error:")
    assert ".." in out
    out = tools.update_concept("/abs/path", body="x")
    assert out.startswith("Error:")


def test_update_refuses_symlinked_concept(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    outside = tmp_path / "outside.txt"
    outside.write_text("do not touch", encoding="utf-8")
    tools = BundleTools(_write_bundle(root, {"linked.md": _concept_doc("Linked", "Body.")}))
    (root / "linked.md").unlink()
    (root / "linked.md").symlink_to(outside)
    out = tools.update_concept("linked", body="New body.")
    assert out.startswith("Error:")
    assert "symlink" in out
    assert outside.read_text(encoding="utf-8") == "do not touch"


def test_update_requires_a_patch_field(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    tools = BundleTools(_write_bundle(root, {"a.md": _concept_doc("A", "Body.")}))
    out = tools.update_concept("a")
    assert out.startswith("Error:")
    assert "nothing to update" in out


# ---------------------------------------------------------------------------
# audit_log
# ---------------------------------------------------------------------------


def test_audit_log_records_write_back_entries(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    tools = BundleTools(Bundle.load(root))
    assert "No write-back" in tools.audit_log()
    tools.write_concept("Alpha", "Body.")
    tools.update_concept("alpha", body="Body two.")
    out = tools.audit_log()
    assert "mcp:write_concept" in out
    assert "mcp:update_concept" in out
    assert "**create**" in out
    assert "**update**" in out
    assert "`alpha`" in out
    audit = root / ".okfsmith" / "audit.jsonl"
    assert audit.is_file()
    entries = _audit_entries(root)
    assert len(entries) == 2
    for entry in entries:
        assert {"action", "actor", "concept_id", "summary", "ts"} <= set(entry)
        assert entry["ts"].endswith("+00:00")
    assert [e["action"] for e in entries] == ["create", "update"]


def test_audit_log_limit(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    tools = BundleTools(Bundle.load(root))
    for i in range(3):
        tools.write_concept(f"Note {i}", "Body.")
    out = tools.audit_log(limit=2)
    assert out.count("mcp:write_concept") == 2


# ---------------------------------------------------------------------------
# validation gate: the validator runs on the result and failures roll back
# ---------------------------------------------------------------------------


def test_write_refused_when_validator_reports_new_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from okfsmith.validate import Finding

    root = tmp_path / "kb"
    tools = BundleTools(Bundle.load(root))

    class FakeReport:
        def __init__(self, errors: list) -> None:
            self.errors = errors

    def fake_check(*args: object, **kwargs: object) -> FakeReport:
        if (root / "alpha.md").exists():
            return FakeReport([Finding("E002", "alpha.md", "simulated failure", "§11.2")])
        return FakeReport([])

    monkeypatch.setattr("okfsmith.validate.check", fake_check)
    out = tools.write_concept("Alpha", "Body.")
    assert out.startswith("Error:")
    assert "E002" in out
    assert "rolled back" in out
    assert not (root / "alpha.md").exists()
    assert _audit_entries(root) == []


def test_write_fails_closed_when_validator_crashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "kb"
    tools = BundleTools(Bundle.load(root))

    def fake_boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("validator down")

    monkeypatch.setattr("okfsmith.validate.check", fake_boom)
    out = tools.write_concept("Alpha", "Body.")
    assert out.startswith("Error:")
    assert "fail closed" in out
    assert not (root / "alpha.md").exists()
    assert _audit_entries(root) == []


def test_update_rolled_back_on_new_validation_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from okfsmith.validate import Finding

    root = tmp_path / "kb"
    doc = _concept_doc("Alpha", "Body.")
    tools = BundleTools(_write_bundle(root, {"alpha.md": doc}))

    class FakeReport:
        def __init__(self, errors: list) -> None:
            self.errors = errors

    seen = {"n": 0}

    def fake_check(*args: object, **kwargs: object) -> FakeReport:
        seen["n"] += 1
        if seen["n"] >= 2:
            return FakeReport([Finding("E001", "alpha.md", "simulated failure", "§11.1")])
        return FakeReport([])

    monkeypatch.setattr("okfsmith.validate.check", fake_check)
    out = tools.update_concept("alpha", body="Changed body.")
    assert out.startswith("Error:")
    assert "rolled back" in out
    assert (root / "alpha.md").read_text(encoding="utf-8") == doc
    assert _audit_entries(root) == []


# ---------------------------------------------------------------------------
# atomicity
# ---------------------------------------------------------------------------


def test_atomic_write_no_half_written_file_on_rename_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "kb"
    tools = BundleTools(Bundle.load(root))

    def boom(src: Path, dst: Path) -> None:
        raise OSError("simulated rename failure")

    monkeypatch.setattr(srv, "_os_replace", boom)
    out = tools.write_concept("Alpha", "Body.")
    assert out.startswith("Error:")
    assert not (root / "alpha.md").exists()
    assert list(root.rglob("*.tmp*")) == []
    assert _audit_entries(root) == []


# ---------------------------------------------------------------------------
# module-level helper behaviour
# ---------------------------------------------------------------------------


def test_coercion_helpers_never_raise() -> None:
    assert srv._coerce_nonempty_text(None) is None
    assert srv._coerce_nonempty_text("   ") is None
    assert srv._coerce_nonempty_text(123) == "123"
    assert srv._coerce_bool("false") is False
    assert srv._coerce_bool("True") is True
    assert srv._coerce_bool(0) is False
    assert srv._coerce_item_list(None) == []
    assert srv._coerce_item_list("x") == ["x"]
    cleaned = srv._strip_verified_markers(
        {"a": {"verified": [{"by": "human:x"}]}, "b": [{"verified": True}]}
    )
    assert cleaned == {"a": {}, "b": [{}]}
    assert isinstance(srv._sanitize_yaml_value({"s": {1, 2}})["s"], str)


# ---------------------------------------------------------------------------
# QA regression tests — independent review findings (2026-09-27)
# One test per confirmed finding: M1-M3 (medium), L1-L8 (low).
# ---------------------------------------------------------------------------


def _machine_confirmed_doc() -> str:
    return _concept_doc(
        "Machine",
        "Machine-verified body.",
        "verified:\n- by: process:nightly\n  at: '2026-01-01T00:00:00+00:00'\n",
    )


def test_m1_symlinked_parent_dir_write_refused(tmp_path: Path) -> None:
    # A symlinked parent directory must not let a write escape the bundle:
    # `sub/evil.md` looks lexically contained while resolving outside it.
    root = tmp_path / "kb"
    outside = tmp_path / "outside"
    outside.mkdir()
    root.mkdir()
    (root / "sub").symlink_to(outside, target_is_directory=True)
    tools = BundleTools(Bundle.load(root))
    out = tools.write_concept("sub/evil", "Hello.")
    assert out.startswith("Error:")
    assert "symlink" in out.lower()
    assert not (outside / "evil.md").exists()
    assert _audit_entries(root) == []


def test_m1_symlinked_parent_dir_preview_refused(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    outside = tmp_path / "outside"
    outside.mkdir()
    root.mkdir()
    (root / "sub").symlink_to(outside, target_is_directory=True)
    tools = BundleTools(Bundle.load(root))
    out = tools.preview_write_concept("sub/evil", "Hello.")
    assert out.startswith("Error:")
    assert "symlink" in out.lower()
    # preview stays side-effect free: nothing created anywhere
    assert _snapshot(root) == {}
    assert list(outside.iterdir()) == []


def test_m2_oversized_sources_list_rejected_fast(tmp_path: Path) -> None:
    import time as _time

    root = tmp_path / "kb"
    tools = BundleTools(Bundle.load(root))
    big = [f"source-{i}" for i in range(5000)]
    started = _time.monotonic()
    out = tools.write_concept("Alpha", "Body.", sources=big)
    elapsed = _time.monotonic() - started
    assert out.startswith("Error:")
    assert "5000" in out and "1000" in out
    assert elapsed < 10  # fail-fast: no copy/sanitize of the huge list
    assert not (root / "alpha.md").exists()
    assert _audit_entries(root) == []


def test_m2_oversized_links_list_rejected_on_update(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    tools = BundleTools(_write_bundle(root, {"alpha.md": _concept_doc("Alpha", "Body.")}))
    out = tools.update_concept("alpha", links=[f"t{i}" for i in range(1001)])
    assert out.startswith("Error:")
    assert "1001" in out
    assert _audit_entries(root) == []


def test_m3_machine_verified_marker_removed_on_body_update(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    tools = BundleTools(_write_bundle(root, {"m.md": _machine_confirmed_doc()}))
    assert "machine-confirmed" in tools.list()
    out = tools.update_concept("m", body="Completely rewritten body.")
    assert "Concept updated" in out
    fm, _ = _parse(root / "m.md")
    assert "verified" not in fm  # stale marker must not survive
    assert trust_tier(fm) == UNVERIFIED
    prov = fm["provenance"]
    assert prov[-1]["action"] == "updated"
    assert prov[-1]["previous_trust"] == "machine-confirmed"
    assert prov[-1]["removed_verified_by"] == ["process:nightly"]


def test_m3_machine_verified_marker_kept_on_title_only_update(tmp_path: Path) -> None:
    # A title-only patch does not replace the verified content, so the
    # machine marker survives it.
    root = tmp_path / "kb"
    tools = BundleTools(_write_bundle(root, {"m.md": _machine_confirmed_doc()}))
    out = tools.update_concept("m", title="Renamed")
    assert "Concept updated" in out
    fm, _ = _parse(root / "m.md")
    assert fm["verified"][0]["by"] == "process:nightly"


def test_l1_mid_body_links_section_replaced_not_stacked(tmp_path: Path) -> None:
    marker = srv._LINKS_SECTION_MARKER
    body = (
        "Intro.\n\n## Links\n\n" + marker + "\n\n- [a](a)\n\nTrailing text.\n"
    )
    root = tmp_path / "kb"
    tools = BundleTools(_write_bundle(root, {"c.md": _concept_doc("C", body)}))
    out = tools.update_concept("c", links=["b"])
    assert "Concept updated" in out
    new_body = (root / "c.md").read_text(encoding="utf-8")
    assert new_body.count("## Links") == 1
    assert "- [b](b)" in new_body
    assert "- [a](a)" not in new_body
    assert "Trailing text." in new_body
    assert "Intro." in new_body


def test_l2_body_only_update_preserves_links_section(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    tools = BundleTools(Bundle.load(root))
    assert "Concept written" in tools.write_concept("C", "Original body.", links=["a"])
    out = tools.update_concept("c", body="New body text.")
    assert "Concept updated" in out
    new_body = (root / "c.md").read_text(encoding="utf-8")
    assert "New body text." in new_body
    assert "## Links" in new_body
    assert "- [a](a)" in new_body


def test_l3_description_refreshed_from_new_body_on_title_update(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    tools = BundleTools(_write_bundle(root, {"c.md": _concept_doc("Old", "Old body.")}))
    out = tools.update_concept("c", title="New", body="Brand new body line.")
    assert "Concept updated" in out
    fm, _ = _parse(root / "c.md")
    assert fm["title"] == "New"
    assert fm["description"] == "Brand new body line."


def test_l4_nested_preview_validates_and_leaves_no_dirs(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    tools = BundleTools(Bundle.load(root))
    before = _snapshot(root)
    out = tools.preview_write_concept("deep/nested/Thing", "Body.")
    assert "Preview: write_concept" in out
    # validation really ran against the nested location (not a silent PASS)
    assert "- **Validation:** PASS" in out
    # side-effect free: no parent dirs left behind
    assert _snapshot(root) == before
    assert not (root / "deep").exists()


def test_l5_stale_preview_orphan_swept_at_session_start(tmp_path: Path) -> None:
    import os
    import time as _time

    root = tmp_path / "kb"
    root.mkdir()
    orphan = root / ".preview-deadbeef-thing.md"
    orphan.write_text("---\ntitle: Orphan\n---\nbody\n", encoding="utf-8")
    old = _time.time() - 3600
    os.utime(orphan, (old, old))
    fresh = root / ".preview-live1234-other.md"
    fresh.write_text("---\ntitle: Fresh\n---\nbody\n", encoding="utf-8")
    tools = BundleTools(Bundle.load(root))  # session start sweeps stale orphans
    assert not orphan.exists()
    assert fresh.exists()  # in-flight previews are never swept
    # The stale orphan must not linger as an in-memory phantom concept
    # even though the bundle was loaded before the sweep (QA L5).
    assert all(
        not c.path.name.startswith(".preview-") for c in tools.bundle.iter_concepts()
    )
    fresh.unlink()


def test_l6_trust_tier_matches_canonical_spec() -> None:
    from okfsmith.core.spec import trust_tier as canonical

    for fm in (
        {},
        {"verified": True},
        {"verified": "yes"},
        {"verified": None},
        {"verified": []},
        {"verified": [{"by": "human:alice"}]},
        {"verified": [{"by": "process:nightly"}]},
    ):
        assert srv._trust_tier_safe(fm) == canonical(fm)


def test_l7_case_insensitive_collision_refused(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    tools = BundleTools(_write_bundle(root, {"Hello.md": _concept_doc("Hello", "Body.")}))
    out = tools.write_concept("hello", "Different body.")
    assert out.startswith("Error:")
    assert "already exists" in out
    # preview reports the collision too
    preview = tools.preview_write_concept("HELLO", "Body.")
    assert "already exists" in preview
    assert _audit_entries(root) == []


def test_l8_rollback_restores_original_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from okfsmith.validate import Finding

    root = tmp_path / "kb"
    root.mkdir()
    original = b"---\r\ntitle: Alpha\r\ntype: Note\r\n---\r\n\r\nBody.\r\n"
    (root / "alpha.md").write_bytes(original)
    tools = BundleTools(Bundle.load(root))

    class FakeReport:
        def __init__(self, errors: list) -> None:
            self.errors = errors

    seen = {"n": 0}

    def fake_check(*args: object, **kwargs: object) -> FakeReport:
        seen["n"] += 1
        if seen["n"] >= 2:  # flag only the post-write pass → rollback
            return FakeReport(
                [Finding("E001", "alpha.md", "simulated failure", "§11.1")]
            )
        return FakeReport([])

    monkeypatch.setattr("okfsmith.validate.check", fake_check)
    out = tools.update_concept("alpha", body="Changed body.")
    assert out.startswith("Error:")
    assert "rolled back" in out
    # byte-identical restore: CRLF endings survive the rollback
    assert (root / "alpha.md").read_bytes() == original
