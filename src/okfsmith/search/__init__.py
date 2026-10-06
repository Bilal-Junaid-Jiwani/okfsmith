"""BM25 full-text search over an OKF knowledge bundle (stdlib only).

Shared ranking core for the ``okfsmith search`` CLI command, the MCP
``BundleTools.search`` tool, and the chat REPL, so all three rank identically.

Design notes:

- :func:`tokenize` is a pure function: lowercase, split on non-alphanumeric
  runs, drop ~50 English stopwords, apply a small deterministic suffix
  stemmer (``sses`` → ``ss``, ``ies`` → ``i``, ``ing``/``ed``/``s`` stripping
  with length guards). The stemmer is intentionally tiny and deterministic —
  it is *not* Porter; e.g. ``news`` stems to ``new``. ``stem`` is memoized
  with an LRU cache (64k entries): token vocabularies repeat heavily
  (Zipf's law), so index builds and query parsing spend ~no time in the
  stemmer after its first pass over a corpus's vocabulary. The cache is a
  pure-function memo — it never changes results.
- Field weighting mirrors the old ``rank_concepts`` intent: id/title ×3,
  description/tags ×2, body ×1. Implemented by repeating a field's tokens
  *weight* times in the document's weighted token stream (BM25F-lite style),
  so document frequency is unaffected by weighting.
- BM25 with ``k1=1.2``, ``b=0.75`` and standard IDF
  ``log(1 + (N - df + 0.5) / (df + 0.5))``.
- Quoted phrases are mandatory adjacency filters; exclusions (``-term``)
  remove documents containing the term. Bare terms score via BM25.
- Results are sorted by score descending, ties broken by concept id, so
  ordering is deterministic across processes.
- The inverted index is built once in :meth:`SearchIndex.from_bundle`
  (document lengths and average document length are precomputed); per-query
  work touches only postings lists, never re-tokenizes the corpus.
- Temporal ranking (:mod:`okfsmith.core.temporal`): hits are partitioned
  into current → outside-validity-window → superseded, each group ordered
  by BM25 score, then trust tier (``human-reviewed`` > ``machine-confirmed``
  > ``unverified``), then ``last_verified`` recency, then concept id.
  Superseded hits are excluded by default (never deleted) and can be
  included with ``include_superseded=True``; an ``as_of`` datetime replays
  the same partitioning at a past or future instant.
"""

from __future__ import annotations

import functools
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from okfsmith.core import temporal as _temporal

if TYPE_CHECKING:
    from okfsmith.core.bundle import Bundle, Concept

__all__ = [
    "STOPWORDS",
    "Query",
    "SearchIndex",
    "TemporalSearchResult",
    "parse_query",
    "search_bundle",
    "search_bundle_detailed",
    "stem",
    "tokenize",
]

#: Split text on runs of non-alphanumeric characters. ``[^\\W_]`` is unicode
#: aware, so ``café`` stays one token.
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)

#: ~50 common English stopwords dropped before stemming.
STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "if", "then", "else", "when",
        "at", "by", "for", "with", "about", "into", "through", "during",
        "before", "after", "above", "below", "to", "from", "up", "down",
        "in", "out", "on", "off", "over", "under", "again", "further",
        "once", "here", "there", "all", "any", "both", "each", "few",
        "more", "most", "other", "some", "such", "no", "nor", "not",
        "only", "own", "same", "so", "than", "too", "very", "can",
        "will", "just", "should", "now", "is", "are", "was", "were",
        "be", "been", "being", "have", "has", "had", "do", "does",
        "did", "of", "as", "it", "its", "this", "that", "these",
        "those",
    }
)

_K1 = 1.2
_B = 0.75


# Stem cache: token vocabularies repeat heavily within a corpus, so the
# per-token suffix-stripping logic below would otherwise re-run ~millions
# of times per index build. ``stem`` is a pure function of its argument,
# so memoizing it cannot change any result. 64k entries cover the
# vocabulary of large bundles; each entry is two short strings.
_STEM_CACHE_SIZE = 65536


@functools.lru_cache(maxsize=_STEM_CACHE_SIZE)
def stem(word: str) -> str:
    """Reduce *word* to a deterministic stem.

    Rules (applied in order): ``sses`` → ``ss`` (``classes`` → ``class``),
    ``ies`` → ``i`` (``studies`` → ``studi``), leave ``ss`` alone, strip a
    trailing ``s`` when the word is longer than 3 chars and the previous
    char is not ``s``/``u`` (``cats`` → ``cat``, ``bus`` stays ``bus``),
    then strip ``ing``/``ed`` with length guards and collapse a doubled
    final consonant (``running`` → ``run``, ``walked`` → ``walk``).
    Pure function; never raises.
    """
    w = word
    if len(w) <= 2:
        return w
    if w.endswith("sses"):
        return w[:-2]
    if w.endswith("ies"):
        return w[:-3] + "i" if len(w) > 4 else w[:-1]
    if w.endswith("ss"):
        return w
    if w.endswith("s") and len(w) > 3 and w[-2] not in "su":
        w = w[:-1]
    for suffix, min_len in (("ing", 6), ("ed", 5)):
        if w.endswith(suffix) and len(w) >= min_len:
            base = w[: -len(suffix)]
            if len(base) >= 3:
                w = base
                if len(w) >= 3 and w[-1] == w[-2] and w[-1] not in "lsz":
                    w = w[:-1]
            break
    return w


def tokenize(text: str) -> list[str]:
    """Lowercase *text*, split on non-alphanumeric runs, drop stopwords,
    and stem each remaining token. Pure function; ``""`` → ``[]``."""
    return [
        stem(tok)
        for tok in _TOKEN_RE.findall((text or "").lower())
        if tok not in STOPWORDS
    ]


@dataclass
class Query:
    """A parsed search query: stemmed tokens, never raw text."""

    terms: list[str] = field(default_factory=list)
    """Bare search terms (stemmed tokens); scored with BM25."""

    phrases: list[list[str]] = field(default_factory=list)
    """Quoted phrases, each a list of stemmed tokens; a document must
    contain every phrase adjacently to be returned."""

    excluded: list[str] = field(default_factory=list)
    """Excluded terms (``-term``); documents containing any are dropped."""

    @property
    def is_empty(self) -> bool:
        """True when the query carries no include terms or phrases."""
        return not self.terms and not self.phrases


def parse_query(query: str) -> Query:
    """Parse *query* into a :class:`Query`.

    Supports quoted phrases (``"knowledge graph"``), exclusions
    (``-deprecated``), and bare terms. An unbalanced quote treats the rest
    of the input as a phrase. Never raises: unparseable input yields an
    empty :class:`Query`.
    """
    q = Query()
    token: list[str] = []
    phrase: list[str] | None = None

    def emit(text: str, excluded: bool) -> None:
        text = text.strip()
        if not text:
            return
        toks = tokenize(text)
        if excluded:
            q.excluded.extend(toks)
        else:
            q.terms.extend(toks)

    text_in = query or ""
    i, n = 0, len(text_in)
    while i < n:
        ch = text_in[i]
        if ch == '"':
            if phrase is not None:
                toks = tokenize("".join(phrase))
                if toks:
                    q.phrases.append(toks)
                phrase = None
            else:
                raw = "".join(token).strip()
                token = []
                if raw.startswith("-"):
                    emit(raw[1:], excluded=True)
                else:
                    emit(raw, excluded=False)
                phrase = []
            i += 1
            continue
        if phrase is not None:
            phrase.append(ch)
        elif ch.isspace():
            raw = "".join(token).strip()
            token = []
            if raw.startswith("-"):
                emit(raw[1:], excluded=True)
            else:
                emit(raw, excluded=False)
        else:
            token.append(ch)
        i += 1
    raw = "".join(token).strip()
    if raw.startswith("-"):
        emit(raw[1:], excluded=True)
    else:
        emit(raw, excluded=False)
    if phrase is not None:  # unbalanced quote: rest is a phrase
        toks = tokenize("".join(phrase))
        if toks:
            q.phrases.append(toks)
    return q


def _field_tokens(concept: Concept) -> list[str]:
    """Weighted token stream for a concept: id/title ×3, description/tags
    ×2, body ×1."""
    fm = concept.frontmatter or {}
    tags = fm.get("tags")
    if tags is None:
        tags = []
    elif isinstance(tags, str):
        tags = [tags]
    elif not isinstance(tags, (list, tuple)):
        # Scalar tags (``tags: 5``) are valid YAML; coerce to a
        # single-entry list rather than crashing iteration (C10).
        tags = [tags]
    fields = (
        (concept.id or "", 3),
        (str(fm.get("title", "") or ""), 3),
        (str(fm.get("description", "") or ""), 2),
        (" ".join(str(t) for t in tags), 2),
        (concept.body or "", 1),
    )
    tokens: list[str] = []
    for text, weight in fields:
        tokens.extend(tokenize(text) * weight)
    return tokens


def _contains_phrase(tokens: list[str], phrase: list[str]) -> bool:
    """True if *phrase* appears as an adjacent run inside *tokens*."""
    n = len(phrase)
    if not n or n > len(tokens):
        return False
    first = phrase[0]
    for i, tok in enumerate(tokens):
        if tok == first and tokens[i : i + n] == phrase:
            return True
    return False


class SearchIndex:
    """In-memory BM25 index over a bundle's concepts.

    Build once with :meth:`from_bundle`, then call :meth:`search` any
    number of times. Indexing is O(corpus size); each query touches only
    the postings lists of its terms.
    """

    def __init__(self) -> None:
        self._concepts: list[Concept] = []
        self._tokens: list[list[str]] = []
        self._doc_lens: list[int] = []
        self._avgdl: float = 0.0
        self._postings: dict[str, dict[int, int]] = {}
        self._idf: dict[str, float] = {}

    @classmethod
    def from_bundle(cls, bundle: Bundle) -> SearchIndex:
        """Build an index over every concept in *bundle*."""
        index = cls()
        for concept in bundle.iter_concepts():
            doc_id = len(index._concepts)
            index._concepts.append(concept)
            tokens = _field_tokens(concept)
            index._tokens.append(tokens)
            index._doc_lens.append(len(tokens))
            counts: dict[str, int] = {}
            for tok in tokens:
                counts[tok] = counts.get(tok, 0) + 1
            for tok, tf in counts.items():
                postings = index._postings.setdefault(tok, {})
                postings[doc_id] = tf
        n_docs = len(index._concepts)
        if n_docs:
            index._avgdl = sum(index._doc_lens) / n_docs
            for tok, postings in index._postings.items():
                df = len(postings)
                index._idf[tok] = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
        return index

    def search(self, query: str, limit: int = 10) -> list[tuple[float, Concept]]:
        """Score concepts against *query*, best first.

        Returns ``[(score, concept), ...]`` sorted by score descending,
        ties broken by concept id (deterministic). Empty queries, queries
        with only stopwords/exclusions, and ``limit <= 0`` return ``[]``.
        """
        parsed = parse_query(query)
        if parsed.is_empty or limit <= 0:
            return []
        excluded_docs: set[int] = set()
        for term in parsed.excluded:
            excluded_docs.update(self._postings.get(term, {}))

        include_terms = list(
            dict.fromkeys(
                parsed.terms + [tok for phrase in parsed.phrases for tok in phrase]
            )
        )
        scores: dict[int, float] = {}
        avgdl = self._avgdl or 1.0
        for term in include_terms:
            postings = self._postings.get(term)
            if not postings:
                continue
            idf = self._idf[term]
            for doc_id, tf in postings.items():
                if doc_id in excluded_docs:
                    continue
                denom = tf + _K1 * (1 - _B + _B * self._doc_lens[doc_id] / avgdl)
                scores[doc_id] = scores.get(doc_id, 0.0) + idf * (tf * (_K1 + 1)) / denom

        for phrase in parsed.phrases:
            for doc_id in [d for d in scores if not _contains_phrase(self._tokens[d], phrase)]:
                del scores[doc_id]

        ranked = sorted(
            scores.items(), key=lambda item: (-item[1], self._concepts[item[0]].id)
        )
        return [(score, self._concepts[doc_id]) for doc_id, score in ranked[:limit]]


def search_bundle(
    bundle: Bundle,
    query: str,
    limit: int = 10,
    *,
    as_of: datetime | None = None,
    include_superseded: bool = False,
) -> list[tuple[float, Concept]]:
    """Drop-in replacement for the old ``rank_concepts``.

    Returns ``[(score, concept), ...]`` best first, same shape as before;
    an empty or blank query returns ``[]``.

    Temporal ranking applies: current concepts first, then concepts outside
    their validity window, then (only with ``include_superseded=True``)
    superseded concepts — demoted, never deleted. ``as_of`` replays the
    partitioning at a past or future instant (default: now, UTC).
    """
    return search_bundle_detailed(
        bundle, query, limit, as_of=as_of, include_superseded=include_superseded
    ).hits


@dataclass
class TemporalSearchResult:
    """Temporal-aware search output: ranked hits plus demotion accounting."""

    hits: list[tuple[float, Concept]]
    """``[(score, concept), ...]`` after temporal partitioning and truncation."""

    as_of: datetime
    """The instant the temporal partitioning was evaluated at (UTC)."""

    superseded_hidden: int
    """Superseded hits excluded from ``hits`` (0 when ``include_superseded``)."""


def search_bundle_detailed(
    bundle: Bundle,
    query: str,
    limit: int = 10,
    *,
    as_of: datetime | None = None,
    include_superseded: bool = False,
) -> TemporalSearchResult:
    """Full temporal search: ranked hits plus demotion accounting.

    Same ranking as :func:`search_bundle`, but also returns the ``as_of``
    instant used and how many superseded hits were hidden, so callers can
    report the demotion honestly instead of silently dropping matches.
    """
    moment = as_of if as_of is not None else _temporal.utcnow()
    if moment.tzinfo is None:
        # Defensive: a naive ``as_of`` from the Python API is read as UTC,
        # matching the CLI (which parses to aware) and avoiding TypeError in
        # aware/naive comparisons downstream.
        moment = moment.replace(tzinfo=timezone.utc)
    if not query or not query.strip() or limit <= 0:
        return TemporalSearchResult([], moment, 0)
    index = SearchIndex.from_bundle(bundle)
    # Fetch every match: temporal exclusion happens after ranking, so the raw
    # BM25 limit must not clip hits that would survive partitioning.
    raw = index.search(query, limit=max(1, len(index._concepts)))
    sindex = _temporal.SupersessionIndex.from_bundle(bundle)
    part = _temporal.partition_hits(raw, sindex, moment)
    hits = part.current + part.windowed
    hidden = len(part.superseded)
    if include_superseded:
        hits.extend((score, concept) for score, concept, _ in part.superseded)
        hidden = 0
    return TemporalSearchResult(hits[:limit], moment, hidden)
