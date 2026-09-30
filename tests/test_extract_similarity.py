"""Tests for similarity-based entity resolution in the extract pipeline.

Covers :func:`okfsmith.extract.pipeline.title_similarity` and the third
(similarity) branch of
:func:`okfsmith.extract.pipeline._find_duplicate` — the dependency-free,
deterministic stand-in for embedding similarity: Jaccard over stemmed title
tokens, thresholded at ``_MIN_TITLE_SIMILARITY``.
"""

import pytest

from okfsmith.core.bundle import Bundle
from okfsmith.extract.pipeline import (
    _MIN_TITLE_SIMILARITY,
    _find_duplicate,
    title_similarity,
)


def _bundle_with_titles(tmp_path, titles):
    bundle = Bundle(tmp_path)
    for i, title in enumerate(titles):
        bundle.write_concept(
            f"concept-{i}",
            {"title": title, "resource": f"doc-{i}.md"},
            f"Body of {title}.",
        )
    return bundle


# ---------------------------------------------------------------------------
# title_similarity unit tests
# ---------------------------------------------------------------------------


def test_identical_titles_score_one():
    assert title_similarity("Incremental Sync", "incremental sync") == 1.0


def test_word_order_does_not_matter():
    assert title_similarity("Sync Guide", "Guide Sync") == 1.0


def test_stemming_unifies_inflections():
    # "syncing" stems to "sync" via the search stemmer.
    assert title_similarity("Syncing Data", "Sync Data") == 1.0


def test_disjoint_titles_score_zero():
    assert title_similarity("Apple Pie", "Quantum Tunneling") == 0.0


def test_empty_titles_score_zero():
    assert title_similarity("", "Something") == 0.0
    assert title_similarity("", "") == 0.0


def test_partial_overlap_between_zero_and_one():
    sim = title_similarity("Incremental Sync", "Incremental Sync Guide")
    assert 0.0 < sim < 1.0
    # {"incremental","sync"} vs {"incremental","sync","guide"} -> 2/3
    assert sim == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# _find_duplicate: branch precedence and similarity behavior
# ---------------------------------------------------------------------------


def test_exact_title_match_still_wins(tmp_path):
    bundle = _bundle_with_titles(tmp_path, ["Incremental Sync"])
    found = _find_duplicate(bundle, "INCREMENTAL  sync!", "other.md")
    assert found is not None
    assert found.frontmatter["title"] == "Incremental Sync"


def test_similarity_branch_merges_near_duplicate(tmp_path):
    bundle = _bundle_with_titles(tmp_path, ["Sync Guide"])
    # Same stemmed token set in a different order: not an exact
    # normalized-title match, but Jaccard 1.0 -> merged.
    found = _find_duplicate(bundle, "Guide Sync", "other.md")
    assert found is not None
    assert found.frontmatter["title"] == "Sync Guide"


def test_similarity_branch_merges_high_overlap(tmp_path):
    bundle = _bundle_with_titles(
        tmp_path, ["Alpha Beta Gamma Delta Epsilon"]
    )
    # 5/6 token overlap ~= 0.833 >= 0.8 threshold -> merged.
    found = _find_duplicate(
        bundle, "Alpha Beta Gamma Delta Epsilon Zeta", "other.md"
    )
    assert found is not None
    assert found.frontmatter["title"] == "Alpha Beta Gamma Delta Epsilon"


def test_similarity_branch_respects_threshold(tmp_path):
    bundle = _bundle_with_titles(tmp_path, ["Apple Pie Recipe"])
    found = _find_duplicate(bundle, "Quantum Tunneling", "other.md")
    assert found is None


def test_low_overlap_titles_do_not_merge(tmp_path):
    bundle = _bundle_with_titles(tmp_path, ["Incremental Sync"])
    # 2/3 overlap < 0.8 threshold: related but distinct scope stays separate.
    found = _find_duplicate(bundle, "Incremental Sync Guide", "other.md")
    assert found is None


def test_similarity_branch_respects_exclude_id(tmp_path):
    bundle = _bundle_with_titles(tmp_path, ["Sync Guide"])
    found = _find_duplicate(
        bundle, "Guide Sync", "other.md", exclude_id="concept-0"
    )
    assert found is None


def test_similarity_tie_break_is_deterministic(tmp_path):
    bundle = _bundle_with_titles(
        tmp_path,
        ["Alpha Beta Gamma Delta Epsilon", "Alpha Beta Gamma Delta Zeta"],
    )
    # Both candidates score 5/6 against the query: the lower id must win,
    # and the outcome must be stable across calls.
    query = "Alpha Beta Gamma Delta Epsilon Zeta"
    first = _find_duplicate(bundle, query, "other.md")
    second = _find_duplicate(bundle, query, "other.md")
    assert first is not None and second is not None
    assert first.id == "concept-0" == second.id


def test_empty_candidate_title_never_matches(tmp_path):
    bundle = _bundle_with_titles(tmp_path, ["Something Real"])
    assert _find_duplicate(bundle, "", "other.md") is None


def test_threshold_constant_is_strict():
    # Merging is destructive: the bar must stay high.
    assert _MIN_TITLE_SIMILARITY >= 0.8
