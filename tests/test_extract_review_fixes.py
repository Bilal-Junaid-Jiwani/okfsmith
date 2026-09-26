"""QA L13 regression tests for :mod:`okfsmith.extract.human_review`.

- A reviewer id containing newlines must be stored single-line in the
  frontmatter ``verified[].by`` (log-forgery hardening; the log line was
  already collapsed — the stored value must match).
- Pre-existing ``verified`` values in any shape (list, bare mapping §5.2,
  legacy scalar) must be *merged*, never silently discarded, when a new
  review is recorded.
"""

from __future__ import annotations

from okfsmith.core.bundle import Bundle
from okfsmith.extract import human_review


def _bundle_with(tmp_path, frontmatter):
    bundle = Bundle(tmp_path)
    bundle.write_concept("notes/t", {"type": "note", "title": "T", **frontmatter}, "body\n")
    return bundle


def test_reviewer_newline_collapsed_in_frontmatter(tmp_path):
    bundle = _bundle_with(tmp_path, {})
    updated = human_review.mark_reviewed(
        bundle, "notes/t", reviewer="alice\ninjected: true"
    )
    by = updated.frontmatter["verified"][-1]["by"]
    assert "\n" not in by
    assert by == "human:alice injected: true"


def test_reviewer_newline_collapsed_in_log(tmp_path):
    bundle = _bundle_with(tmp_path, {})
    human_review.mark_reviewed(bundle, "notes/t", reviewer="alice\ninjected: true")
    log_text = (bundle.root / "log.md").read_text(encoding="utf-8")
    assert "human review by" in log_text
    # The newline is collapsed: nothing forged onto its own log line.
    assert "alice injected: true" in log_text
    assert all(
        "injected: true" not in line or "alice injected: true" in line
        for line in log_text.splitlines()
    )


def test_legacy_scalar_verified_preserved(tmp_path):
    """A pre-existing bare-string ``verified`` must survive a new review."""
    bundle = _bundle_with(tmp_path, {"verified": "legacy:alice"})
    updated = human_review.mark_reviewed(bundle, "notes/t", reviewer="bob")
    entries = updated.frontmatter["verified"]
    assert len(entries) == 2
    assert entries[0] == "legacy:alice"  # preserved verbatim, not discarded
    assert entries[1]["by"] == "human:bob"


def test_bare_mapping_verified_preserved(tmp_path):
    """A §5.2 bare-mapping ``verified`` must survive a new review."""
    legacy = {"by": "process:critic/v1", "at": "2026-01-01T00:00:00+00:00"}
    bundle = _bundle_with(tmp_path, {"verified": dict(legacy)})
    updated = human_review.mark_reviewed(bundle, "notes/t", reviewer="bob")
    entries = updated.frontmatter["verified"]
    assert len(entries) == 2
    assert entries[0] == legacy
    assert entries[1]["by"] == "human:bob"


def test_list_verified_preserved(tmp_path):
    existing = [
        {"by": "human:alice", "at": "2026-01-01T00:00:00+00:00"},
        {"by": "process:critic/v1", "at": "2026-01-02T00:00:00+00:00"},
    ]
    bundle = _bundle_with(tmp_path, {"verified": [dict(e) for e in existing]})
    updated = human_review.mark_reviewed(bundle, "notes/t", reviewer="bob")
    entries = updated.frontmatter["verified"]
    assert entries[:2] == existing
    assert entries[2]["by"] == "human:bob"
    assert len(entries) == 3


def test_reviewer_whitespace_only_still_rejected(tmp_path):
    bundle = _bundle_with(tmp_path, {})
    import pytest

    with pytest.raises(ValueError):
        human_review.mark_reviewed(bundle, "notes/t", reviewer="  \n  ")
