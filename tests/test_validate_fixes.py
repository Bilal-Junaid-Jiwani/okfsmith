"""Regression tests for validator QA fixes: C6, M12, M13, L5/L10, M17.

Covers:
- C6  — symlinked ``.md`` files are skipped by the validation walk, and links
        that resolve through symlinks-outside-root are dead (W001), matching
        ``links.resolve_link`` semantics.
- M12 — CommonMark titles in link targets are stripped before W001/W002.
- M13 — the validator shares ``okfsmith.links.extract_link_targets`` (no
        duplicate extraction regex/logic remains in ``validate/rules.py``).
- L5/L10 — per contract §11 only link *entries* confer reachability; a ``(/)``
        directory entry covers every concept beneath it.
- M17 — ``check()`` accepts a pre-loaded ``Bundle`` and returns the same
        report without re-loading.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from okfsmith import links as links_mod
from okfsmith.core.bundle import Bundle
from okfsmith.validate import check
from okfsmith.validate import rules as rules_mod

_FM = "---\ntype: Note\ntitle: {title}\ndescription: D\n---\n"


def _concept(root: Path, name: str, body: str, title: str = "T") -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_FM.format(title=title) + body, encoding="utf-8")
    return path


def _index(root: Path, text: str) -> None:
    (root / "index.md").write_text("# I\n\n" + text, encoding="utf-8")


def _bundle(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    return root


def _warning_pairs(report, code: str) -> set[tuple[str, str]]:
    return {(f.code, f.file) for f in report.warnings if f.code == code}


# ---------------------------------------------------------------------------
# C6 — symlinked .md skipped; escaping links are W001
# ---------------------------------------------------------------------------


def test_c6_symlinked_md_is_not_a_concept(tmp_path: Path):
    outside = tmp_path / "outside.md"
    outside.write_text("not a bundle file", encoding="utf-8")
    bundle = _bundle(tmp_path / "b")
    _concept(bundle, "a.md", "body\n")
    _index(bundle, "* [A](a) - the a concept\n")
    (bundle / "evil.md").symlink_to(outside)

    report = check(bundle)

    assert report.errors == []
    assert _warning_pairs(report, "W002") == set()
    assert all("evil" not in f.file for f in report.errors + report.warnings)


def test_c6_link_through_escaping_symlink_is_w001(tmp_path: Path):
    outside = tmp_path / "secret.txt"
    outside.write_text("top secret host file", encoding="utf-8")
    bundle = _bundle(tmp_path / "b")
    _concept(bundle, "a.md", "See [ev](evil.md).\n")
    _concept(bundle, "other.md", "body\n")
    _index(bundle, "* [A](a) - x\n* [O](other) - x\n")
    (bundle / "evil.md").symlink_to(outside)

    report = check(bundle)

    assert ("W001", "a.md") in _warning_pairs(report, "W001")
    assert all("evil" not in f.file for f in report.errors + report.warnings)


def test_c6_link_through_inside_symlink_is_fine(tmp_path: Path):
    bundle = _bundle(tmp_path / "b")
    _concept(bundle, "real.md", "body\n")
    (bundle / "alias.md").symlink_to(bundle / "real.md")
    _concept(bundle, "a.md", "See [x](alias.md).\n")
    _index(bundle, "* [A](a) - x\n* [R](real) - x\n")

    report = check(bundle)

    assert ("W001", "a.md") not in _warning_pairs(report, "W001")


def test_c6_parent_dir_symlink_escape_is_w001(tmp_path: Path):
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    (outside_dir / "victim.md").write_text("x", encoding="utf-8")
    bundle = _bundle(tmp_path / "b")
    _concept(bundle, "a.md", "See [v](sub/victim.md).\n")
    _index(bundle, "* [A](a) - x\n")
    (bundle / "sub").symlink_to(outside_dir, target_is_directory=True)

    report = check(bundle)

    assert ("W001", "a.md") in _warning_pairs(report, "W001")


# ---------------------------------------------------------------------------
# M12 — CommonMark titles stripped before W001/W002
# ---------------------------------------------------------------------------


def test_m12_titled_link_to_existing_concept_not_flagged(tmp_path: Path):
    bundle = _bundle(tmp_path / "b")
    _concept(bundle, "b.md", "body\n")
    _concept(bundle, "a.md", 'See [go](b.md "The B page").\n')
    _index(bundle, "* [A](a) - x\n* [B](b) - x\n")

    report = check(bundle)

    assert _warning_pairs(report, "W001") == set()


def test_m12_titled_index_entry_confers_reachability(tmp_path: Path):
    bundle = _bundle(tmp_path / "b")
    _concept(bundle, "one.md", "body\n")
    _index(bundle, '* [One](one.md "The One") - the one concept\n')

    report = check(bundle)

    assert _warning_pairs(report, "W002") == set()


# ---------------------------------------------------------------------------
# M13 — single shared link-extraction implementation
# ---------------------------------------------------------------------------


def test_m13_no_duplicate_link_extraction_in_rules():
    source = inspect.getsource(rules_mod)
    assert "_LINK_RE" not in source
    assert "_iter_link_targets" not in source


def test_m13_rules_uses_shared_extractor():
    assert rules_mod.extract_link_targets is links_mod.extract_link_targets


def test_m13_shared_extractor_strips_commonmark_title():
    assert links_mod.extract_link_targets('[go](b.md "The B page")') == ["b.md"]


# ---------------------------------------------------------------------------
# L5/L10 — reachability per contract §11 (entries only)
# ---------------------------------------------------------------------------


def test_l5_root_directory_entry_covers_everything(tmp_path: Path):
    bundle = _bundle(tmp_path / "b")
    _concept(bundle, "a.md", "body\n")
    _concept(bundle, "sub/deep.md", "body\n")
    _index(bundle, "* [Everything](/) - the whole bundle\n")

    report = check(bundle)

    assert _warning_pairs(report, "W002") == set()


def test_l10_prose_link_does_not_confer_reachability(tmp_path: Path):
    bundle = _bundle(tmp_path / "b")
    _concept(bundle, "listed.md", "body\n")
    _concept(bundle, "prose.md", "body\n")
    _index(
        bundle,
        "* [Listed](listed) - reachable via an entry\n\n"
        "See [prose](prose) for background.\n",
    )

    report = check(bundle)

    assert _warning_pairs(report, "W002") == {("W002", "prose.md")}


def test_l10_bullet_without_link_confers_nothing(tmp_path: Path):
    bundle = _bundle(tmp_path / "b")
    _concept(bundle, "mentioned.md", "body\n")
    _index(bundle, "* just a bullet mentioning mentioned.md with no link\n")

    report = check(bundle)

    assert ("W002", "mentioned.md") in _warning_pairs(report, "W002")


def test_l10_entry_in_subdirectory_index_still_counts(tmp_path: Path):
    bundle = _bundle(tmp_path / "b")
    _concept(bundle, "sub/thing.md", "body\n")
    sub_index = bundle / "sub" / "index.md"
    sub_index.parent.mkdir(parents=True, exist_ok=True)
    sub_index.write_text("# Sub\n\n* [Thing](thing) - x\n", encoding="utf-8")
    _index(bundle, "# Root\n")

    report = check(bundle)

    assert _warning_pairs(report, "W002") == set()


# ---------------------------------------------------------------------------
# M17 — pre-loaded Bundle accepted, same report, no re-load
# ---------------------------------------------------------------------------


def _sample_bundle_dir(tmp_path: Path) -> Path:
    bundle = _bundle(tmp_path / "b")
    _concept(bundle, "a.md", "See [missing](nope).\n")
    _concept(bundle, "orphan.md", "body\n")
    _index(bundle, "* [A](a) - x\n")
    return bundle


def test_m17_preloaded_bundle_matches_path_report(tmp_path: Path):
    path = _sample_bundle_dir(tmp_path)
    bundle = Bundle.load(path)

    via_path = check(str(path))
    via_bundle = check(bundle=bundle)

    assert via_bundle.summary() == via_path.summary()
    assert _warning_pairs(via_bundle, "W001") == {("W001", "a.md")}
    assert _warning_pairs(via_bundle, "W002") == {("W002", "orphan.md")}


def test_m17_does_not_reload_bundle(tmp_path: Path, monkeypatch):
    path = _sample_bundle_dir(tmp_path)
    bundle = Bundle.load(path)

    def _boom(cls, root):
        raise AssertionError("Bundle.load must not be called when bundle is given")

    monkeypatch.setattr(Bundle, "load", classmethod(_boom))

    report = check(bundle=bundle)
    assert report.warnings  # findings still produced from disk


def test_m17_path_forms_still_work(tmp_path: Path):
    path = _sample_bundle_dir(tmp_path)
    from_str = check(str(path))
    from_path = check(path)
    from_kw = check(bundle_path=str(path))
    assert from_str.summary() == from_path.summary() == from_kw.summary()


def test_m17_bundle_wins_over_path(tmp_path: Path):
    path = _sample_bundle_dir(tmp_path)
    bundle = Bundle.load(path)
    report = check(str(tmp_path / "does-not-exist"), bundle=bundle)
    assert _warning_pairs(report, "W001") == {("W001", "a.md")}


def test_m17_requires_an_argument():
    with pytest.raises(ValueError):
        check()


def test_m17_file_path_still_rejected(tmp_path: Path):
    target = tmp_path / "afile"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        check(target)


# ---------------------------------------------------------------------------
# 0.7.9 — validator frontmatter split must use the column-0 closing-fence
# rule (M24), like the bundle loader
# ---------------------------------------------------------------------------


def _fence_bundle(tmp_path: Path, text: str) -> Path:
    """Write *text* as the single concept of a fresh bundle dir."""
    bundle = _bundle(tmp_path / "fb")
    (bundle / "fence.md").write_text(text, encoding="utf-8")
    return bundle


_TRICKY = (
    "---\n"
    "description: |\n"
    "  a poem about fences\n"
    "  ---\n"
    "  still the same description\n"
    "type: Concept\n"
    "title: Fence doc\n"
    "---\n"
    "This is the real body.\n"
)


def test_validator_indented_fence_does_not_truncate_frontmatter():
    # Same raw doc through both splitters: the validator must see exactly
    # the frontmatter/body the bundle loader sees (M24).
    from okfsmith.core.frontmatter import parse_frontmatter

    fm_text, body = rules_mod._split_frontmatter(_TRICKY)
    data, loader_body = parse_frontmatter(_TRICKY)
    assert data["type"] == "Concept"
    assert body == loader_body == "This is the real body.\n"
    assert "type: Concept" in fm_text
    assert fm_text.count("---") == 1  # the indented one, not a fence


def test_validator_no_e002_for_block_scalar_containing_indented_fence(tmp_path: Path):
    # End-to-end: a concept that Bundle.load treats as valid (type parsed,
    # body correct) must not fail validation with a spurious E002.
    bundle = _fence_bundle(tmp_path, _TRICKY)
    loaded = Bundle.load(bundle)
    assert loaded.get("fence").frontmatter["type"] == "Concept"
    assert loaded.get("fence").body == "This is the real body.\n"
    report = check(bundle_path=bundle)
    assert report.is_conformant
    assert not [f for f in report.errors if f.code in ("E001", "E002")]


def test_validator_indented_only_fence_still_e001(tmp_path: Path):
    # The only '---' candidate is indented, so per M24 there is no closing
    # fence: the validator reports E001, exactly as the loader refuses to
    # split (the whole text stays the body).
    from okfsmith.core.frontmatter import parse_frontmatter

    raw = "---\ntitle: x\n  ---\nbody\n"
    data, body = parse_frontmatter(raw)
    assert data == {} and body == raw
    bundle = _fence_bundle(tmp_path, raw)
    report = check(bundle_path=bundle)
    assert {f.code for f in report.errors} == {"E001"}
    assert report.errors[0].message == "no parseable YAML frontmatter block found"


# ---------------------------------------------------------------------------
# 0.7.11 — validator frontmatter split must strip the leading UTF-8 BOM (L22),
# like the bundle loader
# ---------------------------------------------------------------------------


_BOM_CONCEPT = (
    "\ufeff---\n"
    "type: Concept\n"
    "title: BOM doc\n"
    "---\n"
    "Body after BOM.\n"
)


def test_validator_split_strips_bom_like_loader():
    # Same raw doc through both splitters: the validator must see exactly
    # the frontmatter/body the bundle loader sees (L22).
    from okfsmith.core.frontmatter import parse_frontmatter

    fm_text, body = rules_mod._split_frontmatter(_BOM_CONCEPT)
    data, loader_body = parse_frontmatter(_BOM_CONCEPT)
    assert fm_text is not None
    assert data["type"] == "Concept"
    assert body == loader_body == "Body after BOM.\n"
    assert "type: Concept" in fm_text


def test_validator_no_e001_for_bom_prefixed_concept(tmp_path: Path):
    # End-to-end: a BOM-prefixed concept that Bundle.load treats as valid
    # must not fail validation with a spurious E001.
    bundle = _fence_bundle(tmp_path, _BOM_CONCEPT)
    loaded = Bundle.load(bundle)
    assert loaded.get("fence").frontmatter["type"] == "Concept"
    assert loaded.get("fence").body == "Body after BOM.\n"
    report = check(bundle_path=bundle)
    assert report.is_conformant
    assert not [f for f in report.errors if f.code in ("E001", "E002")]


# ---------------------------------------------------------------------------
# 0.7.12 — validator frontmatter split must honor the M28 size guard (20,000
# lines / 1,000,000 chars), like the bundle loader
# ---------------------------------------------------------------------------


def _oversized_by_lines(extra_lines: int) -> str:
    body = "".join(f"k{i}: v\n" for i in range(extra_lines))
    return "---\n" + body + "type: Concept\n---\nBody.\n"


def test_validator_split_honors_m28_line_guard_like_loader():
    # A block with more than 20,000 lines: the loader refuses it (M28) and
    # the validator must see "no parseable frontmatter" too.
    from okfsmith.core.frontmatter import parse_frontmatter

    raw = _oversized_by_lines(20_001)
    fm_text, body = rules_mod._split_frontmatter(raw)
    data, loader_body = parse_frontmatter(raw)
    assert data == {}
    assert fm_text is None
    assert body == loader_body == raw


def test_validator_split_honors_m28_char_guard_like_loader():
    # A block over 1,000,000 chars: refused by the loader, refused by the
    # validator.
    from okfsmith.core.frontmatter import parse_frontmatter

    filler = "v" * 1_000_001
    raw = "---\ntype: Concept\nkey: " + filler + "\n---\nBody.\n"
    fm_text, body = rules_mod._split_frontmatter(raw)
    data, loader_body = parse_frontmatter(raw)
    assert data == {}
    assert fm_text is None
    assert body == loader_body == raw


def test_validator_split_accepts_m28_boundary_like_loader():
    # Exactly at the guard limits the loader still parses; so must the
    # validator (the guard is strictly-greater-than).
    from okfsmith.core.frontmatter import parse_frontmatter

    raw = _oversized_by_lines(19_999)  # 19,999 + 1 type line = 20,000 lines
    fm_text, body = rules_mod._split_frontmatter(raw)
    data, loader_body = parse_frontmatter(raw)
    assert fm_text is not None
    assert data["type"] == "Concept"
    assert body == loader_body == "Body.\n"

    filler = "v" * (1_000_000 - len("type: Concept\nkey: \n"))
    raw2 = "---\ntype: Concept\nkey: " + filler + "\n---\nBody.\n"
    assert len("type: Concept\nkey: " + filler + "\n") == 1_000_000
    fm_text2, body2 = rules_mod._split_frontmatter(raw2)
    data2, loader_body2 = parse_frontmatter(raw2)
    assert fm_text2 is not None
    assert data2["type"] == "Concept"
    assert body2 == loader_body2 == "Body.\n"


def test_validator_e001_for_oversized_frontmatter_concept(tmp_path: Path):
    # End-to-end: a concept whose frontmatter exceeds the M28 guard loads
    # with empty metadata in the bundle loader, and the validator must
    # report E001 (no parseable frontmatter) rather than validating the
    # metadata the runtime will never see.
    bundle = _fence_bundle(tmp_path, _oversized_by_lines(20_001))
    loaded = Bundle.load(bundle)
    assert loaded.get("fence").frontmatter == {}
    report = check(bundle_path=bundle)
    codes = [f.code for f in report.errors]
    assert "E001" in codes
    assert not report.is_conformant
