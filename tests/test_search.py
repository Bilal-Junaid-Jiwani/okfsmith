"""Tests for the BM25 search core (``okfsmith.search``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from okfsmith.core.bundle import Bundle
from okfsmith.search import (
    Query,
    SearchIndex,
    parse_query,
    search_bundle,
    stem,
    tokenize,
)


# ---------------------------------------------------------------- fixtures --
def make_bundle(root: Path) -> Bundle:
    """Hand-built fixture bundle for ranking-quality tests."""
    bundle = Bundle(root)
    bundle.write_concept(
        "alpha",
        {"title": "Knowledge Graph Basics", "description": "intro to graphs"},
        "Some filler body text with nothing special.",
    )
    bundle.write_concept(
        "beta",
        {"title": "Unrelated Notes"},
        "This body mentions knowledge graph deep inside a long paragraph.",
    )
    bundle.write_concept(
        "gamma",
        {"title": "Running Tips", "description": "how to run well"},
        "Lace up and go running every morning.",
    )
    bundle.write_concept(
        "delta",
        {"title": "Morning Run"},
        "A short run clears the head.",
    )
    bundle.write_concept(
        "epsilon",
        {"title": "Scattered Terms"},
        "We have knowledge zebra graph, but not together.",
    )
    # Ubiquitous term "commonword" everywhere; rare term only in zeta.
    for cid in ("alpha", "beta", "gamma", "delta", "epsilon"):
        concept = bundle.get(cid)
        assert concept is not None
        concept.body += " commonword"
    bundle.write_concept(
        "zeta",
        {"title": "Rare Find"},
        "commonword and the ultra rare zyxwvterm appear here.",
    )
    return bundle


@pytest.fixture()
def bundle(tmp_path: Path) -> Bundle:
    return make_bundle(tmp_path)


# ------------------------------------------------------------- tokenizer ----
class TestTokenize:
    def test_lowercase_and_split(self):
        assert tokenize("Hello, World!") == ["hello", "world"]

    def test_splits_on_non_alphanumeric_runs(self):
        assert tokenize("foo---bar_baz.qux") == ["foo", "bar", "baz", "qux"]

    def test_drops_stopwords(self):
        assert tokenize("the quick brown fox") == ["quick", "brown", "fox"]

    def test_stopword_only_is_empty(self):
        assert tokenize("the and of to a") == []

    def test_empty_string(self):
        assert tokenize("") == []

    def test_unicode_tokens_preserved(self):
        assert tokenize("Café naïve") == ["café", "naïve"]

    def test_numbers_kept(self):
        assert tokenize("RFC 3986") == ["rfc", "3986"]

    def test_pure_function_no_mutation(self):
        text = "Running RUNNING"
        assert tokenize(text) == ["run", "run"]
        assert text == "Running RUNNING"


class TestStemmer:
    @pytest.mark.parametrize(
        "word,expected",
        [
            ("classes", "class"),  # sses -> ss
            ("studies", "studi"),  # ies -> i
            ("running", "run"),  # ing + undouble
            ("walked", "walk"),  # ed
            ("plays", "play"),  # trailing s
            ("cats", "cat"),
            ("bus", "bus"),  # too short to strip s
            ("as", "as"),  # length guard
            ("sing", "sing"),  # ing guard (stem would be < 3)
            ("feed", "feed"),  # ed guard
            ("glass", "glass"),  # ss left alone
            ("dogs", "dog"),
        ],
    )
    def test_stem_cases(self, word: str, expected: str):
        assert stem(word) == expected

    def test_stem_is_deterministic(self):
        assert stem("running") == stem("running")


# ---------------------------------------------------------- query parser ----
class TestParseQuery:
    def test_bare_terms(self):
        q = parse_query("knowledge graph")
        assert isinstance(q, Query)
        assert q.terms == ["knowledge", "graph"]
        assert q.phrases == []
        assert q.excluded == []

    def test_quoted_phrase(self):
        q = parse_query('"knowledge graph" basics')
        assert q.phrases == [["knowledge", "graph"]]
        assert q.terms == ["basic"]

    def test_exclusion(self):
        q = parse_query("graph -deprecated")
        assert q.terms == ["graph"]
        assert q.excluded == ["deprecat"]  # stem("deprecated")

    def test_unbalanced_quote_is_phrase(self):
        q = parse_query('foo "bar baz')
        assert q.terms == ["foo"]
        assert q.phrases == [["bar", "baz"]]

    def test_empty_query(self):
        q = parse_query("")
        assert q.is_empty
        assert q.terms == [] and q.phrases == [] and q.excluded == []

    def test_whitespace_only(self):
        assert parse_query("   ").is_empty

    def test_stopword_only_query_is_empty(self):
        assert parse_query("the and of").is_empty

    def test_never_raises(self):
        for weird in ['"', '""', "-", "--", '"a', 'a"', '-"x y', "  "]:
            parse_query(weird)  # must not raise

    def test_multiple_phrases(self):
        q = parse_query('"red blue" "green yellow"')
        assert q.phrases == [["red", "blue"], ["green", "yellow"]]

    def test_phrase_terms_are_stemmed(self):
        q = parse_query('"running tests"')
        assert q.phrases == [["run", "test"]]


# ---------------------------------------------------------------- ranking ---
class TestRanking:
    def test_title_match_outranks_body_match(self, bundle: Bundle):
        hits = search_bundle(bundle, "knowledge graph")
        ids = [c.id for _, c in hits]
        # alpha: phrase in title (x3); beta: phrase only in body (x1)
        assert ids.index("alpha") < ids.index("beta")

    def test_stemming_matches_inflections(self, bundle: Bundle):
        ids = {c.id for _, c in search_bundle(bundle, "running")}
        assert {"gamma", "delta"} <= ids  # "running" matches "run"/"running"

    def test_phrase_requires_adjacency(self, bundle: Bundle):
        ids = [c.id for _, c in search_bundle(bundle, '"knowledge graph"')]
        assert "alpha" in ids and "beta" in ids
        assert "epsilon" not in ids  # "knowledge of the graph" is not adjacent

    def test_exclusion_removes_hits(self, bundle: Bundle):
        ids = [c.id for _, c in search_bundle(bundle, "graph -basics")]
        assert "alpha" not in ids
        assert "beta" in ids

    def test_idf_demotes_ubiquitous_terms(self, bundle: Bundle):
        # "zyxwvterm" is rare, "commonword" is everywhere: the rare-only
        # concept must win a combined query.
        hits = search_bundle(bundle, "commonword zyxwvterm")
        assert hits and hits[0][1].id == "zeta"

    def test_scores_descending(self, bundle: Bundle):
        hits = search_bundle(bundle, "knowledge graph running")
        scores = [s for s, _ in hits]
        assert scores == sorted(scores, reverse=True)
        assert all(isinstance(s, float) for s in scores)

    def test_ties_broken_by_concept_id(self, tmp_path: Path):
        bundle = Bundle(tmp_path)
        # ids tokenize to equal-length streams ("1"/"2" both kept) so the
        # two docs tie on score; written out of id order on purpose.
        for cid in ("tie-2", "tie-1"):
            bundle.write_concept(
                cid, {"title": "Identical Title"}, "Identical body words."
            )
        hits = search_bundle(bundle, "identical")
        assert [c.id for _, c in hits] == ["tie-1", "tie-2"]

    def test_deterministic_across_runs(self, bundle: Bundle):
        first = [(s, c.id) for s, c in search_bundle(bundle, "knowledge graph run")]
        for _ in range(3):
            again = [(s, c.id) for s, c in search_bundle(bundle, "knowledge graph run")]
            assert again == first


# --------------------------------------------------------------- edge cases --
class TestEdgeCases:
    def test_empty_query_returns_empty(self, bundle: Bundle):
        assert search_bundle(bundle, "") == []
        assert search_bundle(bundle, "   ") == []

    def test_stopword_only_query_returns_empty(self, bundle: Bundle):
        assert search_bundle(bundle, "the and of") == []

    def test_no_matches_returns_empty(self, bundle: Bundle):
        assert search_bundle(bundle, "qqqzzz") == []

    def test_limit_respected(self, bundle: Bundle):
        hits = search_bundle(bundle, "knowledge", limit=1)
        assert len(hits) == 1

    def test_limit_zero_returns_empty(self, bundle: Bundle):
        assert search_bundle(bundle, "knowledge", limit=0) == []

    def test_empty_bundle(self, tmp_path: Path):
        assert search_bundle(Bundle(tmp_path), "anything") == []

    def test_search_index_api(self, bundle: Bundle):
        index = SearchIndex.from_bundle(bundle)
        hits = index.search("knowledge graph", limit=3)
        assert len(hits) <= 3
        assert all(isinstance(score, float) for score, _ in hits)
        # search() also treats blank queries as empty
        assert index.search("   ") == []

    def test_missing_frontmatter_fields(self, tmp_path: Path):
        bundle = Bundle(tmp_path)
        bundle.write_concept("bare", {}, "just a body mentioning mango")
        hits = search_bundle(bundle, "mango")
        assert [c.id for _, c in hits] == ["bare"]

    def test_tags_and_description_indexed(self, tmp_path: Path):
        bundle = Bundle(tmp_path)
        bundle.write_concept(
            "tagged",
            {"title": "Nope", "description": "kiwi fruit", "tags": ["papaya"]},
            "plain body",
        )
        assert {c.id for _, c in search_bundle(bundle, "kiwi")} == {"tagged"}
        assert {c.id for _, c in search_bundle(bundle, "papaya")} == {"tagged"}
