"""Performance, parity, and determinism tests for the BM25 search core.

Covers the perf + parity acceptance criteria of
``~/workspace/okfsmith-audit/feature-spec-search.md`` (section 1, section 5):

* ``SearchIndex.from_bundle`` over 5,000 synthetic concepts completes in < 5 s.
* Building the index and running 20 representative queries takes < 5 s total.
* For a fixed query, the ordered concept-id list is identical across
  ``search_bundle(...)``, the CLI ``search --format json`` output, and the
  MCP ``BundleTools.search`` path (ordered ids are compared, never scores).
* The same query run twice yields identical ordered results.

Integration status: the ``okfsmith.search`` package, the CLI ``search``
command, and the MCP BM25 integration are being built concurrently by other
agents. Anything not yet in place is *skipped* with a clear
``PENDING-INTEGRATION`` reason rather than failed, so this file stays green
while the feature lands. Nothing in this file edits product code.
"""

from __future__ import annotations

import inspect
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from okfsmith.core.bundle import Bundle, Concept
from okfsmith.mcp_server.server import BundleTools

PENDING = "PENDING-INTEGRATION"

# Budgets are generous but firm (spec section 5: 5 s total for 5k docs + queries).
INDEX_BUDGET_S = 5.0
INDEX_AND_QUERIES_BUDGET_S = 5.0

_PARITY_QUERY = "knowledge graph"
_PARITY_LIMIT = 10


def _require_search():
    """Import ``okfsmith.search``, skipping as PENDING-INTEGRATION if absent."""
    return pytest.importorskip(
        "okfsmith.search",
        reason=f"{PENDING}: okfsmith.search package not yet implemented",
    )


# ---------------------------------------------------------------------------
# Synthetic 5,000-concept bundle (perf tests)
# ---------------------------------------------------------------------------

_SYN_MODIFIERS = (
    "knowledge semantic distributed incremental federated temporal "
    "probabilistic hierarchical adaptive robust".split()
)
_SYN_TOPICS = (
    "graph ontology taxonomy pipeline workflow schema entity relation "
    "mapping query".split()
)
_SYN_NOUNS = (
    "engine service model store cache report dashboard snapshot ledger "
    "catalog".split()
)
_SYN_VERBS = (
    "build validate index transform link merge prune export ingest audit "
    "tune".split()
)
_SYN_FILLER = (
    "the and for with from this that each every into over under about "
    "across within without data text document concept system process method "
    "approach result study analysis design pattern practice guide note "
    "overview summary detail record entry item field value list set map "
    "table view panel card block unit layer stage phase step task job run "
    "batch stream event log trace metric score rank level class kind sort "
    "form state mode case base core root leaf node edge path tree web net "
    "grid cloud edge core hub spoke ring star mesh chain loop cycle".split()
)
_SYN_TYPES = ("Concept", "Metric", "Playbook", "Guide")


def _synthetic_concepts(n: int = 5000) -> list[Concept]:
    """Build *n* deterministic synthetic concepts with varied title/body lengths.

    Titles run 3-8 words, bodies 20-399 words; vocabulary is drawn from fixed
    pools so generation is identical on every run (no randomness).
    """
    concepts = []
    pool = _SYN_MODIFIERS + _SYN_TOPICS + _SYN_NOUNS + _SYN_VERBS + _SYN_FILLER
    pool_len = len(pool)
    for i in range(n):
        title_words = [
            _SYN_MODIFIERS[i % len(_SYN_MODIFIERS)],
            _SYN_TOPICS[(i // 3) % len(_SYN_TOPICS)],
            _SYN_NOUNS[(i // 7) % len(_SYN_NOUNS)],
        ]
        title_words += [_SYN_VERBS[(i + k) % len(_SYN_VERBS)] for k in range(i % 6)]
        title = " ".join(title_words).title()

        body_len = 20 + (i * 37) % 380  # 20..399 words
        body_words = [pool[(i * 13 + k * 7) % pool_len] for k in range(body_len)]
        # Every 50th concept carries a "deprecated" marker for exclusion queries.
        if i % 50 == 0:
            body_words[0] = "deprecated"
            body_words[1] = "legacy"
        body = " ".join(body_words) + "."

        topic = _SYN_TOPICS[i % len(_SYN_TOPICS)]
        modifier = _SYN_MODIFIERS[(i // len(_SYN_TOPICS)) % len(_SYN_MODIFIERS)]
        frontmatter = {
            "title": title,
            "type": _SYN_TYPES[i % len(_SYN_TYPES)],
            "description": f"A {modifier} {topic} {_SYN_NOUNS[i % len(_SYN_NOUNS)]}.",
            "tags": [topic, modifier],
        }
        concepts.append(
            Concept(
                id=f"perf/c{i:04d}",
                path=Path(f"perf/c{i:04d}.md"),
                frontmatter=frontmatter,
                body=body,
            )
        )
    return concepts


@pytest.fixture(scope="module")
def perf_bundle(tmp_path_factory: pytest.TempPathFactory) -> Bundle:
    """Bundle of 5,000 synthetic concepts, assembled in memory.

    Built in memory (not written to disk) so the timed sections measure
    index construction, not filesystem I/O.
    """
    bundle = Bundle(tmp_path_factory.mktemp("perf-bundle"))
    # Private attribute on purpose: there is no public in-memory bulk-add API,
    # and writing 5,000 files would measure disk speed, not index speed.
    bundle._concepts = {c.id: c for c in _synthetic_concepts(5000)}  # noqa: SLF001
    return bundle


_REPRESENTATIVE_QUERIES = [
    "graph",
    "ontology",
    "knowledge graph",
    "semantic taxonomy",
    '"knowledge graph"',
    "pipeline -deprecated",
    "entity relation mapping",
    "inference engine",
    "federated query",
    "temporal index",
    "probabilistic reasoning",
    "schema mapping",
    "distributed workflow",
    "hierarchical taxonomy",
    "incremental pipeline",
    "attribute entity",
    "rule engine",
    "the graph",
    "nonexistenttermxyz",
    '"semantic taxonomy" ontology',
]


def test_from_bundle_completes_within_budget(perf_bundle: Bundle) -> None:
    """``SearchIndex.from_bundle`` on 5,000 concepts must finish in < 5 s."""
    search = _require_search()
    start = time.perf_counter()
    index = search.SearchIndex.from_bundle(perf_bundle)
    elapsed = time.perf_counter() - start
    assert hasattr(index, "search"), "from_bundle did not return a usable index"
    assert elapsed < INDEX_BUDGET_S, (
        f"from_bundle took {elapsed:.2f}s for 5,000 concepts "
        f"(budget {INDEX_BUDGET_S}s)"
    )


def test_index_build_plus_twenty_queries_within_budget(perf_bundle: Bundle) -> None:
    """Index build + 20 representative queries must total < 5 s (spec section 5)."""
    search = _require_search()
    assert len(_REPRESENTATIVE_QUERIES) == 20
    start = time.perf_counter()
    index = search.SearchIndex.from_bundle(perf_bundle)
    for query in _REPRESENTATIVE_QUERIES:
        results = index.search(query, limit=10)
        assert isinstance(results, list)
    elapsed = time.perf_counter() - start
    assert elapsed < INDEX_AND_QUERIES_BUDGET_S, (
        f"index + 20 queries took {elapsed:.2f}s "
        f"(budget {INDEX_AND_QUERIES_BUDGET_S}s)"
    )


# ---------------------------------------------------------------------------
# Small hand-built bundle (parity + determinism tests)
# ---------------------------------------------------------------------------

# (id, title, description, tags, body). Every concept mentions "graph";
# all but two also mention "knowledge", with the terms spread across title,
# description, tags, and body so the fixed query exercises real ranking.
_PARITY_SPECS: list[tuple[str, str, str, list[str], str]] = [
    ("kb/graph-overview", "Knowledge Graph Overview",
     "Service architecture for the knowledge graph.",
     ["knowledge", "graph"],
     "The knowledge graph stores entities and relations. Query the knowledge "
     "graph with pattern matching. Every knowledge graph deployment needs a schema."),
    ("kb/graph-querying", "Querying the Knowledge Graph",
     "How to query the graph.",
     ["graph", "query"],
     "Graph queries traverse entities. The knowledge graph query planner "
     "optimizes traversals."),
    ("kb/graph-schema", "Graph Schema Design",
     "Designing schemas for graph data.",
     ["schema"],
     "A knowledge graph schema defines entity types and relation types."),
    ("kb/ontology-basics", "Ontology Basics",
     "Ontologies for knowledge organization.",
     ["ontology"],
     "An ontology gives a knowledge graph its vocabulary. Without an ontology, "
     "the graph is just triples."),
    ("kb/taxonomy-guide", "Taxonomy Guide",
     "Building taxonomies.",
     ["taxonomy"],
     "Taxonomies classify entities in the knowledge graph. Each taxonomy node "
     "maps to graph nodes."),
    ("kb/entity-linking", "Entity Linking",
     "Linking mentions to graph entities.",
     ["entity"],
     "Entity linking resolves mentions against the knowledge graph. The graph "
     "stores canonical entities."),
    ("kb/relation-extraction", "Relation Extraction",
     "Extracting relations from text.",
     ["relation"],
     "Relations connect entities in the graph. Extracted relations enrich the "
     "knowledge graph."),
    ("kb/search-tuning", "Search Tuning",
     "Tuning full-text search.",
     ["search"],
     "Tune ranking with a knowledge graph of synonyms. The graph maps query "
     "terms to concepts."),
    ("kb/legacy-exporter", "Legacy Graph Exporter",
     "Deprecated exporter, do not use.",
     ["deprecated", "graph"],
     "This deprecated exporter dumps the knowledge graph to CSV. Deprecated "
     "since v0.1."),
    ("kb/index-design", "Index Design",
     "Index structures for graph stores.",
     ["index"],
     "The graph index accelerates knowledge graph lookups. Index every entity id."),
    ("kb/embedding-notes", "Embedding Notes",
     "Graph embeddings overview.",
     ["embedding"],
     "Embeddings encode graph structure. Train on the knowledge graph with "
     "random walks."),
    ("kb/reasoning-rules", "Reasoning Rules",
     "Inference over the graph.",
     ["reasoning"],
     "Rules infer new edges in the knowledge graph. The graph reasoner applies "
     "rules iteratively."),
    ("kb/pipeline-intro", "Ingestion Pipeline",
     "Pipeline overview.",
     ["pipeline"],
     "The pipeline loads documents into the graph store."),
    ("kb/workflow-notes", "Workflow Notes",
     "Workflow tips.",
     ["workflow"],
     "Workflows orchestrate jobs. One workflow rebuilds the knowledge graph "
     "nightly."),
    ("kb/dashboard-guide", "Dashboard Guide",
     "Dashboard building.",
     ["dashboard"],
     "Dashboards visualize metrics. A dashboard can render the knowledge graph."),
    ("kb/backup-policy", "Backup Policy",
     "Backup procedures.",
     ["ops"],
     "Back up the graph store daily. The knowledge graph backup includes the "
     "schema."),
    ("kb/access-control", "Access Control",
     "ACLs for concepts.",
     ["security"],
     "Access control lists guard the graph. Knowledge graphs need per-entity ACLs."),
    ("kb/versioning", "Concept Versioning",
     "Versioning concepts.",
     ["ops"],
     "Version every concept. The knowledge graph keeps history per graph node."),
    ("kb/glossary", "Glossary",
     "Term definitions.",
     ["docs"],
     "Graph: a structure of nodes and edges. Knowledge: what the graph stores."),
    ("kb/faq", "FAQ",
     "Frequently asked questions.",
     ["docs"],
     "Q: What is the knowledge graph? A: A graph of entities and relations."),
]


@pytest.fixture(scope="module")
def parity_bundle(tmp_path_factory: pytest.TempPathFactory) -> Bundle:
    """Small on-disk bundle with varied 'knowledge graph' mentions."""
    bundle = Bundle(tmp_path_factory.mktemp("parity-bundle"))
    for cid, title, description, tags, body in _PARITY_SPECS:
        bundle.write_concept(
            cid,
            {"title": title, "type": "Concept", "description": description,
             "tags": tags},
            body,
        )
    return bundle


def _search_bundle_ids(bundle: Bundle, query: str, limit: int) -> list[str]:
    """Ordered concept ids from ``search_bundle`` (the reference ordering)."""
    search = _require_search()
    return [concept.id for _, concept in search.search_bundle(bundle, query, limit)]


def test_search_bundle_is_deterministic(parity_bundle: Bundle) -> None:
    """Same bundle + query twice -> identical ordered concept ids."""
    first = _search_bundle_ids(parity_bundle, _PARITY_QUERY, _PARITY_LIMIT)
    second = _search_bundle_ids(parity_bundle, _PARITY_QUERY, _PARITY_LIMIT)
    assert len(first) > 1, "parity fixture query should return multiple hits"
    assert first == second


# ---------------------------------------------------------------------------
# CLI + MCP parity helpers
# ---------------------------------------------------------------------------

def _cli_search_ids(bundle_dir: Path, query: str, limit: int) -> list[str]:
    """Run ``okfsmith search BUNDLE QUERY --format json``; return ordered ids.

    Skips as PENDING-INTEGRATION when the ``search`` command is not registered
    yet (concurrent workstream).
    """
    proc = subprocess.run(
        [sys.executable, "-m", "okfsmith", "search", str(bundle_dir), query,
         "--format", "json", "--limit", str(limit)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    combined = proc.stderr + proc.stdout
    if "No such command" in combined:
        pytest.skip(f"{PENDING}: CLI `search` command not yet implemented")
    assert proc.returncode == 0, (
        f"CLI search failed (exit {proc.returncode}): {proc.stderr.strip()}"
    )
    payload = json.loads(proc.stdout)
    return [str(item["id"]) for item in payload["results"]]


_MCP_RESULT_LINE_RE = re.compile(r"^\s*-\s*\*\*([^*]+?)\*\*", re.MULTILINE)


def _mcp_search_ids(bundle: Bundle, query: str, limit: int) -> list[str]:
    """Extract the ordered concept ids from ``BundleTools.search`` output.

    The MCP tool returns a markdown list whose result lines start with
    ``- **<id>**``; continuation lines (descriptions) do not start with ``-``.
    """
    text = BundleTools(bundle).search(query, limit=limit)
    return _MCP_RESULT_LINE_RE.findall(text)


def test_parity_cli_json_matches_search_bundle(parity_bundle: Bundle) -> None:
    """CLI ``search --format json`` order == ``search_bundle`` order."""
    expected = _search_bundle_ids(parity_bundle, _PARITY_QUERY, _PARITY_LIMIT)
    assert len(expected) > 1, "parity fixture query should return multiple hits"
    cli_ids = _cli_search_ids(parity_bundle.root, _PARITY_QUERY, _PARITY_LIMIT)
    assert cli_ids == expected


def _mcp_uses_bm25_engine() -> bool:
    """Detect whether the MCP ``search`` path uses the BM25 engine yet.

    Per the feature spec (§3) the MCP integration reimplements
    ``rank_concepts`` as a thin shim over the new engine *with a deprecation
    note in its docstring*; either that note or a direct reference to the
    search package in ``BundleTools.search`` counts as "integrated".
    """
    from okfsmith.mcp_server import server as mcp_server

    shimmed = "deprecat" in (mcp_server.rank_concepts.__doc__ or "").lower()
    try:
        source = inspect.getsource(mcp_server.BundleTools.search)
    except (OSError, TypeError):
        source = ""
    direct = any(
        marker in source for marker in ("search_bundle", "SearchIndex", "okfsmith.search")
    )
    return shimmed or direct


def test_parity_mcp_matches_search_bundle(parity_bundle: Bundle) -> None:
    """MCP ``BundleTools.search`` order == ``search_bundle`` order."""
    if not _mcp_uses_bm25_engine():
        pytest.skip(
            f"{PENDING}: MCP `search` not yet reimplemented over the BM25 engine "
            "(still the legacy substring ranker)"
        )
    expected = _search_bundle_ids(parity_bundle, _PARITY_QUERY, _PARITY_LIMIT)
    assert len(expected) > 1, "parity fixture query should return multiple hits"
    mcp_ids = _mcp_search_ids(parity_bundle, _PARITY_QUERY, _PARITY_LIMIT)
    assert mcp_ids == expected


def test_cli_search_deterministic_across_processes(parity_bundle: Bundle) -> None:
    """Two CLI subprocess runs of the same query return identical ordered ids."""
    first = _cli_search_ids(parity_bundle.root, _PARITY_QUERY, _PARITY_LIMIT)
    second = _cli_search_ids(parity_bundle.root, _PARITY_QUERY, _PARITY_LIMIT)
    assert first == second


def test_mcp_search_ids_extractable(parity_bundle: Bundle) -> None:
    """The id-extraction helper works against the real MCP output.

    Runs today (no search package needed): validates the parity fixture and
    the extraction regex against the current ``BundleTools.search`` output,
    and keeps passing once the MCP path is reimplemented over the BM25 engine.
    """
    ids = _mcp_search_ids(parity_bundle, _PARITY_QUERY, _PARITY_LIMIT)
    assert len(ids) > 1, "parity fixture query should return multiple hits"
    known = {concept.id for concept in parity_bundle.iter_concepts()}
    assert set(ids) <= known, f"unknown ids in MCP output: {set(ids) - known}"
    assert len(ids) == len(set(ids)), "duplicate ids in MCP output"
