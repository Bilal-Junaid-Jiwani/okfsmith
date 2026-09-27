"""MCP server over an OKF v0.2 knowledge bundle (FastMCP).

The bundle is loaded **once** at server startup; every tool call afterwards
reads from the in-memory :class:`~okfsmith.core.bundle.Bundle`. All tools are
read-only — nothing here can modify the bundle.

FastMCP is imported lazily so the base ``okfsmith`` install stays light.
Without the ``mcp`` extra installed, :func:`build_server` / :func:`serve`
raise a clear :class:`RuntimeError` explaining how to install it.

Tool outputs are compact markdown (not giant JSON), suitable as an agent's
reading UI. Entry point for progressive disclosure: ``index()`` → the root
``index.md`` → ``get()`` / ``search()`` for detail.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from okfsmith.core import frontmatter as _fm
from okfsmith.core import temporal as _temporal
from okfsmith.core.bundle import Bundle, Concept
from okfsmith.core.spec import MACHINE_CONFIRMED, UNVERIFIED, trust_tier

#: Regex for markdown links ``[text](target)``; footnote refs ``[^x]`` are
#: excluded by requiring the char before ``[`` to not be ``^``.
_LINK_RE = re.compile(r"(?<!\^)\[([^\]]+)\]\(([^)\s]+)\)")


def _coerce_tags(frontmatter: Mapping) -> list[str]:
    """Return the concept's ``tags`` frontmatter as a list of strings.

    Hand-written frontmatter often carries a scalar (``tags: 5``,
    ``tags: single``) — valid YAML that would otherwise crash iteration.
    A scalar becomes a single-entry list; ``None`` becomes ``[]``. Never
    raises on malformed input (C10).
    """
    tags = frontmatter.get("tags")
    if tags is None:
        return []
    if isinstance(tags, str):
        return [tags]
    if isinstance(tags, list):
        return [str(t) for t in tags]
    return [str(tags)]


def _trust_tier_safe(frontmatter: Any) -> str:
    """Derive the trust tier, tolerating scalar ``verified`` frontmatter.

    ``verified: yes`` (a bare YAML bool) is the most natural thing a human
    writes, but :func:`~okfsmith.core.spec.trust_tier` expects a mapping or
    list. A non-iterable scalar therefore degrades per the §5.3 trust-tier
    rules instead of raising: a truthy scalar claims verification without
    naming a ``human:`` actor → ``"machine-confirmed"``; a falsy/absent
    scalar → ``"unverified"``. Never raises on malformed input (C10).
    """
    if not isinstance(frontmatter, Mapping):
        return UNVERIFIED
    verified = frontmatter.get("verified")
    if verified is None or isinstance(verified, (Mapping, list, tuple, set)):
        return trust_tier(frontmatter)
    return MACHINE_CONFIRMED if verified else UNVERIFIED


def _coerce_limit(limit: Any, default: int) -> int:
    """Coerce *limit* to a non-negative int; unparseable input → *default*.

    Direct Python callers (tests, the chat REPL) can pass any object where
    the MCP transport would normally enforce an int — a clean fallback here
    keeps the tools' "never an exception" contract (L16).
    """
    try:
        coerced = int(limit)
    except (TypeError, ValueError):
        coerced = default
    return max(coerced, 0)


#: Hard ceiling for ``max_chunks`` on every tool (evidence-budget cap).
_MAX_CHUNKS = 50

#: Hard ceiling for ``traverse`` depth: bounds the BFS fan-out on dense graphs.
_MAX_TRAVERSE_DEPTH = 3

#: Lines per text chunk for the single-document tools (``get``, ``index``);
#: paging cuts at chunk boundaries so markdown is never split mid-line.
_TEXT_CHUNK_LINES = 50

#: Token-budget estimate: tokens ≈ characters / 4 (documented approximation).
_TOKEN_CHARS_PER_TOKEN = 4

#: Continuation-token payload version, so future formats stay distinguishable.
_CONT_TOKEN_VERSION = 1


def _coerce_chunks(value: Any, default: int) -> int:
    """Coerce ``max_chunks`` to ``1.._MAX_CHUNKS``; unparseable → *default*.

    Mirrors :func:`_coerce_limit` but with the evidence-budget ceiling: the
    tools' "never an exception" contract covers garbage budget input too.
    """
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        coerced = default
    return min(max(coerced, 1), _MAX_CHUNKS)


def _coerce_max_tokens(value: Any) -> int | None:
    """Coerce ``max_tokens`` to a positive int; ``None``/unparseable → ``None``.

    ``None`` means "no token budget" — the default, which keeps every
    existing tool's output byte-identical unless the caller opts in.
    """
    if value is None:
        return None
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return None
    return coerced if coerced > 0 else None


def _encode_continuation(offset: int) -> str:
    """Encode a unit offset as an opaque continuation token."""
    payload = json.dumps(
        {"v": _CONT_TOKEN_VERSION, "o": max(int(offset), 0)},
        separators=(",", ":"),
    )
    encoded = base64.urlsafe_b64encode(payload.encode("ascii")).decode("ascii")
    return encoded.rstrip("=")


def _decode_continuation(token: Any) -> int | None:
    """Decode a continuation token to a unit offset; ``None`` when invalid.

    Never raises: over-long tokens, bad base64, bad JSON, a wrong payload
    version, or a non-integer/negative offset all decode to ``None`` so the
    caller can return a clean error instead of a traceback.
    """
    if not isinstance(token, str) or not token or len(token) > 256:
        return None
    try:
        padded = token + "=" * (-len(token) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, binascii.Error, UnicodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("v") != _CONT_TOKEN_VERSION:
        return None
    offset = payload.get("o")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        return None
    return offset


def _fit_budget(
    page: list[str], start: int, total: int, max_tokens: int | None
) -> tuple[list[str], int, int]:
    """Trim *page* to the approximate token budget, whole units only.

    Units are added in order while the running estimate (characters // 4)
    stays within *max_tokens*; at least one unit is always kept so a tiny
    budget still returns something. Returns ``(kept, resume_offset,
    remaining)`` where the offset resumes at the first unshown unit.
    """
    kept = page
    if max_tokens is not None:
        kept = []
        used = 0
        for unit in page:
            cost = max(1, len(unit) // _TOKEN_CHARS_PER_TOKEN)
            if kept and used + cost > max_tokens:
                break
            kept.append(unit)
            used += cost
    resume = start + len(kept)
    return kept, resume, total - resume


def _text_chunks(text: str, lines_per_chunk: int = _TEXT_CHUNK_LINES) -> list[str]:
    """Split *text* into chunks of at most *lines_per_chunk* lines."""
    lines = text.splitlines()
    return [
        "\n".join(lines[i : i + lines_per_chunk])
        for i in range(0, max(len(lines), 1), lines_per_chunk)
    ]


def _concept_sha256(concept: Concept) -> str:
    """Hex SHA-256 of the concept's markdown body; never raises."""
    try:
        return hashlib.sha256(concept.body.encode("utf-8")).hexdigest()
    except Exception:
        return "unavailable"


def _concept_title(concept: Concept) -> str:
    """Frontmatter title, falling back to the concept id; never raises."""
    try:
        title = concept.frontmatter.get("title")
    except Exception:
        return concept.id
    if title is None:
        return concept.id
    return str(title).strip() or concept.id


def _sha256_file(path: Path) -> str | None:
    """Hex SHA-256 of a file's bytes (streamed); ``None`` on any I/O failure."""
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(65536), b""):
                digest.update(block)
        return digest.hexdigest()
    except (OSError, ValueError):
        return None


_FOOTNOTE_DEF_RE = re.compile(r"^\[\^([^\]]+)\]:\s*(.*?)\s*$", re.MULTILINE)
_FOOTNOTE_REF_RE = re.compile(r"\[\^([^\]]+)\](?!:)")


def _footnote_definitions(body: str) -> dict[str, str]:
    """Map footnote label → definition text (first definition wins)."""
    definitions: dict[str, str] = {}
    for label, text in _FOOTNOTE_DEF_RE.findall(body or ""):
        definitions.setdefault(label.strip(), text.strip())
    return definitions


def _footnote_refs(body: str) -> list[str]:
    """Footnote labels referenced in *body*, in order, deduplicated."""
    seen: list[str] = []
    for label in _FOOTNOTE_REF_RE.findall(body or ""):
        label = label.strip()
        if label and label not in seen:
            seen.append(label)
    return seen


def _coerce_sources(frontmatter: Any) -> list[Any]:
    """The concept's ``sources`` frontmatter as a list; never raises (C10).

    Hand-written frontmatter often carries a scalar (``sources: some-url``)
    — a scalar becomes a single-entry list, ``None`` becomes ``[]``.
    """
    if not isinstance(frontmatter, Mapping):
        return []
    sources = frontmatter.get("sources")
    if sources is None:
        return []
    if isinstance(sources, (str, Mapping)):
        return [sources]
    if isinstance(sources, (list, tuple)):
        return list(sources)
    return [sources]


def _render_source_entry(entry: Any) -> str:
    """One-line human rendering of a ``sources[]`` entry; never raises."""
    if isinstance(entry, Mapping):
        bits = []
        for key in ("id", "title", "resource", "author"):
            value = entry.get(key)
            if value:
                bits.append(f"{key}: {_one_line(str(value), 100)}")
        if bits:
            return "; ".join(bits)
        return _one_line(str(dict(entry)), 120)
    return _one_line(str(entry), 140)


def _relation_matches(link_text: str, target: str, relation_filter: str) -> bool:
    """True when *relation_filter* describes the link.

    The OKF link model has no explicit relation type, so the filter matches
    the prose-derived relation (the link text) or the target id — prefix or
    substring — case-insensitively.
    """
    needle = relation_filter.lower()
    return needle in link_text.lower() or needle in target.lower()


def _load_sync_state(bundle: Bundle) -> dict[str, Any] | None:
    """Read ``<bundle>/.okfsmith/sync-state.json``; ``None`` when unusable.

    Never raises: a missing file, a symlink (never followed — same rule as
    :meth:`Bundle.load`), invalid JSON, or a non-mapping payload all degrade
    to ``None`` so callers fall back to their documented behaviour.
    """
    try:
        from okfsmith.core.sync import SYNC_STATE_FILENAME
        from okfsmith.parsers.dedup import MANIFEST_DIRNAME
    except ImportError:
        return None
    try:
        path = bundle.root / MANIFEST_DIRNAME / SYNC_STATE_FILENAME
        if path.is_symlink() or not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _decode_state_key(key: Any) -> str:
    """Reverse the sync-state key encoding (``sync-key-b64:``); never raises."""
    prefix = "sync-key-b64:"
    if isinstance(key, str) and key.startswith(prefix):
        try:
            raw = base64.b64decode(key[len(prefix) :].encode("ascii"))
            return raw.decode("utf-8", errors="replace")
        except (ValueError, binascii.Error, UnicodeError):
            return key
    return str(key)


def _rank_concepts_legacy(
    bundle: Bundle, query: str, limit: int
) -> list[tuple[float, Concept]]:
    """Original case-insensitive substring scoring, best first.

    Fallback used when the BM25 engine (``okfsmith.search``) is unavailable
    or raises on malformed frontmatter. A word matching the concept id or
    title scores 3, description/tags 2, body 1; results are sorted by score
    descending, then concept id, and capped at *limit*.
    """
    words = [w for w in query.lower().split() if w]
    if not words:
        return []
    scored: list[tuple[float, Concept]] = []
    for concept in bundle.iter_concepts():
        fm = concept.frontmatter
        title = str(fm.get("title", ""))
        description = str(fm.get("description", ""))
        tag_text = " ".join(_coerce_tags(fm))
        score = 0.0
        for word in words:
            if word in concept.id.lower() or word in title.lower():
                score += 3
            if word in description.lower() or word in tag_text.lower():
                score += 2
            if word in concept.body.lower():
                score += 1
        if score:
            scored.append((score, concept))
    scored.sort(key=lambda item: (-item[0], item[1].id))
    return scored[: max(limit, 0)]


def rank_concepts(
    bundle: Bundle, query: str, limit: int = 10
) -> list[tuple[float, Concept]]:
    """Score bundle concepts against *query*, best first.

    Thin shim over the BM25 engine
    :func:`okfsmith.search.search_bundle` (stdlib-only, shared with the
    ``okfsmith search`` CLI and the interactive chat REPL so all three rank
    identically): BM25 with field weights (id/title ×3, description/tags
    ×2, body ×1), stemming, quoted phrases, and ``-exclusions``. When the
    engine is not importable — or raises on malformed hand-written
    frontmatter it does not tolerate yet — the original substring scoring
    is used as a fallback, so this never raises (C10). Results are always
    returned score-descending with ties broken by concept id, whatever the
    engine hands back. The ``(bundle, query, limit=10)`` signature is kept
    for back-compat. Returns ``[]`` for an empty query.
    """
    limit = _coerce_limit(limit, 10)
    if not isinstance(query, str):
        query = "" if query is None else str(query)
    if not query.split():
        return []
    try:
        from okfsmith.search import search_bundle
    except ImportError:
        return _rank_concepts_legacy(bundle, query, limit)
    try:
        hits = search_bundle(bundle, query, limit)
    except (TypeError, AttributeError):
        # Scalar frontmatter (e.g. ``tags: 5``) the engine does not
        # tolerate: degrade to the legacy scorer rather than crash — the
        # MCP tools' "never an exception" contract wins over ranking
        # parity on malformed input (C10).
        return _rank_concepts_legacy(bundle, query, limit)
    # Enforce the documented contract (score desc, id tiebreak) on whatever
    # the engine returns; a no-op once the engine sorts correctly itself.
    hits.sort(key=lambda item: (-item[0], item[1].id))
    return hits[:limit]


def _require_fastmcp() -> Any:
    """Import ``fastmcp`` (the ``mcp`` extra) or raise a helpful error."""
    try:
        from fastmcp import FastMCP

        return FastMCP
    except ImportError as exc:
        raise RuntimeError(
            "The MCP server requires the 'mcp' extra: "
            "install it with `pip install \"okfsmith[mcp]\"`."
        ) from exc


def _one_line(text: str, width: int = 140) -> str:
    """First non-empty line of *text*, whitespace-collapsed and truncated."""
    for line in text.splitlines():
        line = " ".join(line.split())
        if line:
            return line if len(line) <= width else line[: width - 1] + "…"
    return ""


def _concept_label(concept: Concept) -> str:
    """One-line markdown summary of a concept: id, type, title, trust tier.

    The trust tier is derived defensively: scalar ``verified`` frontmatter
    (``verified: yes`` in hand-written YAML) degrades per the §5.3 rules
    instead of raising (C10).
    """
    fm = concept.frontmatter
    ctype = str(fm.get("type", "?"))
    title = str(fm.get("title", concept.id))
    tier = _trust_tier_safe(fm)
    return f"**{concept.id}** — `{ctype}` · *{tier}* — {title}"


def _description(concept: Concept) -> str:
    """The concept's one-line description (frontmatter or first body line)."""
    desc = concept.frontmatter.get("description")
    if desc:
        return _one_line(str(desc))
    return _one_line(concept.body)


def _bundle_links(target: str) -> str | None:
    """Normalize a markdown link target to a bundle concept id, or None.

    Accepts bundle-relative absolute links (``/finance/profit``) and plain
    relative ids (``finance/profit``). External URLs, anchors, and fragment
    links return ``None``.
    """
    if not target or target.startswith(("http://", "https://", "mailto:", "#")):
        return None
    candidate = target.split("#", 1)[0].strip().lstrip("/")
    return candidate or None


class BundleTools:
    """The eight MCP tool functions, bound to one loaded bundle.

    Instances are created by :func:`build_server`; each method is registered
    as an MCP tool. They are also directly callable (as the tests do), with
    no MCP transport required.

    Every method returns compact markdown text. Lookup failures return a
    plain-English ``Error: ...`` string — never an exception — so agents get
    a recoverable message instead of a tool crash. Every method also accepts
    the evidence-budget parameters ``max_chunks`` (items per response, hard
    cap 50), ``max_tokens`` (approximate output budget, ``None`` = unbounded)
    and ``continuation_token`` (opaque paging token); budgets cut at whole
    units, never mid-item, and an invalid token returns a clean error.
    """

    def __init__(self, bundle: Bundle) -> None:
        self.bundle = bundle
        # Built once: the bundle is loaded once at server startup, so the
        # supersession graph is stable for the server's lifetime.
        self._sindex = _temporal.SupersessionIndex.from_bundle(bundle)

    # -- shared rendering ----------------------------------------------------
    def _render_paged(
        self,
        *,
        title: str,
        whole: str,
        units: list[str],
        notes: list[str] | tuple[str, ...] = (),
        max_chunks: Any,
        chunk_default: int,
        max_tokens: Any,
        continuation_token: Any,
    ) -> str:
        """Render a budgeted, pageable markdown response from *units*.

        *units* are pre-rendered markdown lines (section headers included);
        *notes* are first-page-only context lines (supersession notices,
        query mode). Applies the continuation offset, the ``max_chunks``
        page size, and the approximate ``max_tokens`` budget — always at
        whole-unit boundaries, never mid-item. When everything fits on the
        first page with no budgets applied, returns *whole* byte-identical
        (the backward-compat fast path: old callers see old output).
        Otherwise returns ``# {title}`` (``(continued)`` when resuming), the
        page's units, and — when units remain — the ``…[truncated, N more]``
        marker plus the next ``continuation_token``. An invalid token
        returns a clean error, never a traceback.
        """
        start = 0
        if continuation_token:
            decoded = _decode_continuation(continuation_token)
            if decoded is None:
                return (
                    "Error: invalid `continuation_token` — it is malformed, "
                    "from another query, or for a newer token format. Omit "
                    "it to start from the first page."
                )
            start = decoded
        chunks = _coerce_chunks(max_chunks, chunk_default)
        budget = _coerce_max_tokens(max_tokens)
        flow = list(notes) + units if start == 0 else units
        start = min(start, len(flow))
        page = flow[start : start + chunks]
        kept, resume, remaining = _fit_budget(page, start, len(flow), budget)
        if start == 0 and remaining == 0:
            return whole
        lines = [f"# {title} (continued)" if start else f"# {title}"]
        lines.extend(kept)
        if remaining > 0:
            lines.append(f"…[truncated, {remaining} more]")
            lines.append(
                f'_Pass `continuation_token="{_encode_continuation(resume)}"` '
                "for the next page._"
            )
        return "\n".join(lines)

    def _temporal_note(self, concept: Concept, now: Any) -> str | None:
        """Human note for a non-current temporal status; ``None`` when current.

        Never raises: temporal fields are untrusted frontmatter (P2).
        """
        try:
            status = self._sindex.status(concept, now)
        except Exception:
            return None
        if status.name == "current":
            return None
        if status.name == "superseded":
            return f"superseded by `{status.superseded_by}`"
        return status.name.replace("_", " ")  # "expired" / "not yet valid"

    def _is_superseded(self, concept: Concept, now: Any) -> bool:
        """True when *concept* is superseded at *now*; never raises."""
        try:
            return self._sindex.status(concept, now).name == "superseded"
        except Exception:
            return False

    def _currency_rank(self, concept: Concept, now: Any) -> int:
        """Sort key for currency-aware ordering (P2): current, windowed, superseded."""
        try:
            name = self._sindex.status(concept, now).name
        except Exception:
            return 0
        return {"current": 0, "superseded": 2}.get(name, 1)

    # -- progressive disclosure entry point ---------------------------------
    def index(
        self,
        max_chunks: int = 50,
        max_tokens: int | None = None,
        continuation_token: str | None = None,
    ) -> str:
        """Return the bundle's root index.md — the map of the whole knowledge base.

        This is the starting point for progressive disclosure: the index
        lists every concept with a one-line summary. Read this first to
        orient yourself, then use `search` to find concepts by keyword and
        `get` to read a concept in full. Each index entry's concept id can
        be passed to `get`, `neighbors`, or `list` for deeper exploration.

        Evidence budgets: `max_chunks` caps the 50-line text chunks returned
        (default 50, hard cap 50), `max_tokens` is an approximate output
        budget (``None`` = unbounded), and `continuation_token` pages through
        long indexes — budgets cut at chunk boundaries, never mid-line.

        Returns the raw index.md text; if the bundle has no index.md, says
        so and suggests `list` instead.
        """
        if not self.bundle.index_text:
            return (
                "This bundle has no root index.md. Use the `list` tool to see "
                "all concepts, or `search` to find one by keyword."
            )
        return self._render_paged(
            title="Bundle index",
            whole=self.bundle.index_text,
            units=_text_chunks(self.bundle.index_text),
            max_chunks=max_chunks,
            chunk_default=50,
            max_tokens=max_tokens,
            continuation_token=continuation_token,
        )

    # -- inventory -----------------------------------------------------------
    def list(
        self,
        filter_type: str = "",
        limit: int = 50,
        max_chunks: int = 50,
        max_tokens: int | None = None,
        continuation_token: str | None = None,
    ) -> str:
        """List every concept in the bundle: id, type, trust tier, and title.

        Use this for a full inventory of the knowledge base, or to narrow
        down by concept type. `filter_type` matches the concept's frontmatter
        `type` (case-insensitive substring, e.g. "Metric", "Playbook",
        "Attested Computation"). `limit` caps the number of rows returned
        (non-numeric input falls back to the default 50).

        Evidence budgets: `max_chunks` caps the rows per response (default
        50, hard cap 50), `max_tokens` is an approximate output budget, and
        `continuation_token` pages through long inventories.

        Returns a markdown list ordered by concept id. For the full text of
        any concept, pass its id to `get`.
        """
        concepts = list(self.bundle.iter_concepts())
        if filter_type:
            needle = str(filter_type).lower()
            concepts = [
                c
                for c in concepts
                if needle in str(c.frontmatter.get("type", "")).lower()
            ]
        concepts = concepts[: _coerce_limit(limit, 50)]
        if not concepts:
            return (
                "No concepts found."
                if not filter_type
                else f"No concepts found with type matching {filter_type!r}."
            )
        units = [f"- {_concept_label(c)}" for c in concepts]
        title = f"Concepts ({len(units)})"
        return self._render_paged(
            title=title,
            whole=f"# {title}\n\n" + "\n".join(units),
            units=units,
            max_chunks=max_chunks,
            chunk_default=50,
            max_tokens=max_tokens,
            continuation_token=continuation_token,
        )

    # -- keyword search ------------------------------------------------------
    def _search_hits(
        self, query: str, limit: int, include_superseded: bool
    ) -> tuple[list[tuple[float, Concept]], int]:
        """Ranked ``(score, concept)`` hits plus the superseded-hidden count.

        Currency-aware (P2): superseded concepts are hidden unless
        *include_superseded* — the same default the ``okfsmith search`` CLI
        uses. Falls back to :func:`rank_concepts` when the BM25 engine is
        unavailable or rejects malformed frontmatter, so the tools' "never
        an exception" contract wins over ranking parity on hostile input.
        """
        try:
            from okfsmith.search import search_bundle_detailed
        except ImportError:
            return rank_concepts(self.bundle, query, limit), 0
        try:
            result = search_bundle_detailed(
                self.bundle,
                query,
                limit,
                include_superseded=bool(include_superseded),
            )
        except (TypeError, AttributeError):
            return rank_concepts(self.bundle, query, limit), 0
        return result.hits, result.superseded_hidden

    def search(
        self,
        query: str,
        limit: int = 10,
        include_superseded: bool = False,
        max_chunks: int = 10,
        max_tokens: int | None = None,
        continuation_token: str | None = None,
    ) -> str:
        """Search concepts by id, title, description, tags, and body text.

        Full-text BM25 ranking (stdlib-only ``okfsmith.search`` engine,
        shared with the ``okfsmith search`` CLI and the chat REPL so all
        three rank identically): field weights id/title ×3,
        description/tags ×2, body ×1, with stemming, quoted phrases, and
        ``-exclusions``. `limit` caps the number of results (default 10;
        non-numeric input falls back to 10).

        Currency-aware (P2): superseded concepts are hidden by default and
        reported as a count; pass `include_superseded=True` to reveal them
        (shown last). Evidence budgets: `max_chunks` caps the hits per
        response (default 10, hard cap 50), `max_tokens` is an approximate
        output budget, and `continuation_token` pages through long result
        lists.

        Returns a compact markdown list: concept id, type, trust tier
        (`human-reviewed` > `machine-confirmed` > `unverified`), title, and
        a one-line description. Use `get` with a result's id to read the
        full concept. A missing or blank query returns a clean error,
        never an exception.
        """
        if not isinstance(query, str) or not query.split():
            return "Error: `query` is empty — provide a keyword to search for."
        limit = _coerce_limit(limit, 10)
        hits, hidden = self._search_hits(query, limit, include_superseded)
        if not hits:
            return f"No concepts match {query!r}. Try broader keywords or use `list`."
        units = [f"- {_concept_label(c)}\n  {_description(c)}" for _, c in hits]
        notes = (
            [
                f"_{hidden} superseded concept(s) hidden — "
                "pass `include_superseded=True` to reveal._"
            ]
            if hidden
            else []
        )
        title = f"Search: {query} ({len(units)} result(s))"
        whole = f"# {title}\n\n" + "\n".join(units)
        if notes:
            whole += "\n\n" + "\n".join(notes)
        return self._render_paged(
            title=title,
            whole=whole,
            units=units,
            notes=notes,
            max_chunks=max_chunks,
            chunk_default=10,
            max_tokens=max_tokens,
            continuation_token=continuation_token,
        )

    # -- full concept --------------------------------------------------------
    def get(
        self,
        concept_id: str,
        max_chunks: int = 50,
        max_tokens: int | None = None,
        continuation_token: str | None = None,
    ) -> str:
        """Read one concept in full: its YAML frontmatter followed by its markdown body.

        `concept_id` is the concept's path id, e.g. "finance/revenue" (see
        `list` or `search` for valid ids). The frontmatter carries the OKF
        metadata — `type`, `title`, `description`, `tags`, trust info
        (`generated` / `verified`), and `sources` — and the body is the
        knowledge content itself.

        Evidence budgets: `max_chunks` caps the 50-line text chunks returned
        (default 50, hard cap 50), `max_tokens` is an approximate output
        budget (``None`` = unbounded), and `continuation_token` pages through
        long documents — budgets cut at chunk boundaries, never mid-line.

        Returns the concept document (frontmatter + body). If the id does
        not exist, returns a clean "not found" error suggesting how to find
        valid ids.
        """
        concept = self.bundle.get(concept_id) if isinstance(concept_id, str) else None
        if concept is None:
            return (
                f"Error: concept {concept_id!r} not found in this bundle. "
                "Use `list` to see all concept ids or `search` to find one "
                "by keyword."
            )
        whole = _fm.serialize_frontmatter(concept.frontmatter, concept.body)
        return self._render_paged(
            title=f"Get {concept_id}",
            whole=whole,
            units=_text_chunks(whole),
            max_chunks=max_chunks,
            chunk_default=50,
            max_tokens=max_tokens,
            continuation_token=continuation_token,
        )

    # -- link graph ----------------------------------------------------------
    def neighbors(
        self,
        concept_id: str,
        max_chunks: int = 50,
        max_tokens: int | None = None,
        continuation_token: str | None = None,
    ) -> str:
        """Show a concept's outgoing links and incoming backlinks.

        Outgoing links are the markdown links in the concept's own body.
        Incoming links (backlinks) are found by scanning every other
        concept's body for links pointing at this concept. Each link is
        shown with its id, type, and the link text — which is the
        prose-derived description of the relation (e.g. "computed by [the
        revenue computation](/computations/revenue)").

        Evidence budgets: `max_chunks` caps the link rows per response
        (default 50, hard cap 50), `max_tokens` is an approximate output
        budget, and `continuation_token` pages through long neighborhoods.

        Returns two sections, "Outgoing" and "Incoming". A missing concept
        returns a clean "not found" error.
        """
        concept = self.bundle.get(concept_id) if isinstance(concept_id, str) else None
        if concept is None:
            return (
                f"Error: concept {concept_id!r} not found in this bundle. "
                "Use `list` to see all concept ids or `search` to find one "
                "by keyword."
            )

        outgoing: list[tuple[str, str]] = []
        for text, target in _LINK_RE.findall(concept.body):
            linked_id = _bundle_links(target)
            if linked_id:
                outgoing.append((linked_id, text.strip()))

        incoming: list[tuple[str, str, str]] = []
        for other in self.bundle.iter_concepts():
            if other.id == concept_id:
                continue
            for text, target in _LINK_RE.findall(other.body):
                linked_id = _bundle_links(target)
                if linked_id == concept_id:
                    incoming.append(
                        (
                            other.id,
                            str(other.frontmatter.get("type", "?")),
                            text.strip(),
                        )
                    )
                    break

        def _fmt_out(linked_id: str, text: str) -> str:
            linked = self.bundle.get(linked_id)
            label = _concept_label(linked) if linked else f"**{linked_id}** (missing)"
            return f"- {label} — linked as: \"{text}\""

        def _fmt_in(source_id: str, source_type: str, text: str) -> str:
            return f"- **{source_id}** (`{source_type}`) — linked as: \"{text}\""

        units = [f"## Outgoing ({len(outgoing)})"]
        if outgoing:
            units.extend(_fmt_out(lid, text) for lid, text in outgoing)
        else:
            units.append("_No outgoing links._")
        units.append("")
        units.append(f"## Incoming ({len(incoming)})")
        if incoming:
            units.extend(_fmt_in(sid, stype, text) for sid, stype, text in incoming)
        else:
            units.append("_No incoming links._")
        title = f"Links for {concept_id}"
        return self._render_paged(
            title=title,
            whole=f"# {title}\n\n" + "\n".join(units),
            units=units,
            max_chunks=max_chunks,
            chunk_default=50,
            max_tokens=max_tokens,
            continuation_token=continuation_token,
        )


    # -- graph traversal -----------------------------------------------------
    def traverse(
        self,
        concept_id: str,
        depth: int = 1,
        relation_filter: str | None = None,
        include_superseded: bool = False,
        max_chunks: int = 10,
        max_tokens: int | None = None,
        continuation_token: str | None = None,
    ) -> str:
        """Walk the concept link graph outward from one concept (breadth-first).

        `concept_id` is the entry point; `depth` is how many link hops to
        expand (capped at 3 — deeper requests are capped, not rejected).
        `relation_filter` optionally restricts which links are followed: the
        OKF link model has no explicit relation type, so the filter matches
        the prose-derived relation (the link text, e.g. "computed by") or the
        target id (prefix or substring), case-insensitively.

        Currency-aware (P2): superseded concepts are hidden by default (and
        never traversed through); pass `include_superseded=True` to reveal
        them. Within each depth level, current concepts sort before
        expired/not-yet-valid ones. The walk is cycle-safe (a visited set)
        and deterministic (links expand in target-id order).

        Evidence budgets: `max_chunks` caps the concepts per response
        (default 10, hard cap 50), `max_tokens` is an approximate output
        budget, and `continuation_token` pages through large neighborhoods.

        Returns one section per depth level with a one-line summary per
        concept plus the link text that led to it. A missing concept
        returns a clean "not found" error.
        """
        concept = self.bundle.get(concept_id) if isinstance(concept_id, str) else None
        if concept is None:
            return (
                f"Error: concept {concept_id!r} not found in this bundle. "
                "Use `list` to see all concept ids or `search` to find one "
                "by keyword."
            )
        requested_depth = _coerce_limit(depth, 1)
        max_depth = min(requested_depth, _MAX_TRAVERSE_DEPTH)
        filt = str(relation_filter).strip().lower() if relation_filter else ""
        now = _temporal.utcnow()

        visited = {concept.id}
        levels: list[list[tuple[str, str, Concept]]] = []
        hidden = 0
        dangling = 0
        frontier = [concept.id]
        for _ in range(max_depth):
            found: list[tuple[str, str, Concept]] = []
            next_frontier: list[str] = []
            for parent_id in frontier:
                parent = self.bundle.get(parent_id)
                if parent is None:
                    continue
                targets: dict[str, str] = {}
                for text, target in _LINK_RE.findall(parent.body or ""):
                    linked_id = _bundle_links(target)
                    if linked_id and linked_id not in targets:
                        targets[linked_id] = text.strip()
                for linked_id, text in sorted(targets.items()):
                    if filt and not _relation_matches(text, linked_id, filt):
                        continue
                    if linked_id in visited:
                        continue
                    visited.add(linked_id)
                    node = self.bundle.get(linked_id)
                    if node is None:
                        dangling += 1
                        continue
                    if not include_superseded and self._is_superseded(node, now):
                        hidden += 1
                        continue
                    found.append((parent_id, text, node))
                    next_frontier.append(linked_id)
            if not found:
                break
            found.sort(
                key=lambda item: (self._currency_rank(item[2], now), item[2].id)
            )
            levels.append(found)
            frontier = next_frontier

        notes: list[str] = []
        start_note = self._temporal_note(concept, now)
        if start_note:
            notes.append(f"_Note: **{concept.id}** is {start_note}._")
        if requested_depth > _MAX_TRAVERSE_DEPTH:
            notes.append(f"_Depth capped at {_MAX_TRAVERSE_DEPTH}._")
        if filt:
            notes.append(
                f'_Relation filter: "{relation_filter}" — matched against '
                "link text and target id._"
            )
        total = sum(len(items) for items in levels)
        notes.append(
            f"_Reached {total} concept(s) across {len(levels)} depth level(s) "
            f"(depth ≤ {max_depth})._"
        )
        if hidden:
            notes.append(
                f"_{hidden} superseded concept(s) hidden — "
                "pass `include_superseded=True` to reveal._"
            )
        if dangling:
            notes.append(f"_{dangling} link(s) point to missing concepts._")

        units: list[str] = []
        for depth_no, items in enumerate(levels, start=1):
            units.append(f"## Depth {depth_no} ({len(items)})")
            for parent_id, text, node in items:
                line = f'- {_concept_label(node)} — via "{text}" from `{parent_id}`'
                note = self._temporal_note(node, now)
                if note:
                    line += f" _({note})_"
                units.append(line)
        if not units:
            units.append("_No linked concepts found within the requested depth._")

        title = f"Traverse from {concept_id} (depth ≤ {max_depth})"
        head = [f"# {title}", ""]
        if notes:
            head.extend([*notes, ""])
        return self._render_paged(
            title=title,
            whole="\n".join(head + units),
            units=units,
            notes=notes,
            max_chunks=max_chunks,
            chunk_default=10,
            max_tokens=max_tokens,
            continuation_token=continuation_token,
        )

    # -- provenance ----------------------------------------------------------
    def _ingested_sources(self, concept_id: str) -> list[tuple[str, str | None]]:
        """``(source path, sha256)`` sync-state records listing *concept_id*.

        Walks the ingested-source manifest (``sync-state.json``); returns
        ``[]`` when there is no usable state. Never raises.
        """
        state = _load_sync_state(self.bundle)
        if not state:
            return []
        records = state.get("sources")
        if not isinstance(records, dict):
            return []
        found: list[tuple[str, str | None]] = []
        for key, record in records.items():
            if not isinstance(record, dict):
                continue
            try:
                raw_concepts = record.get("concepts")
                ids = (
                    [str(cid) for cid in raw_concepts]
                    if isinstance(raw_concepts, (list, tuple))
                    else []
                )
                if concept_id in ids:
                    sha = record.get("sha256")
                    found.append(
                        (_decode_state_key(key), sha if isinstance(sha, str) else None)
                    )
            except Exception:
                continue
        return sorted(found)

    def provenance(
        self,
        concept_id: str,
        max_chunks: int = 50,
        max_tokens: int | None = None,
        continuation_token: str | None = None,
    ) -> str:
        """Trace a concept's provenance: every claim back to its source.

        Walks the concept's `sources[]` frontmatter and its footnote
        references (`[^label]` → their `[^label]:` definitions), then links
        each source to the ingested-source manifest (`sync-state.json`) when
        one exists — showing the source file path and its SHA-256 digest at
        ingest time. Malformed `sources` frontmatter (scalars, wrong types)
        degrades to best-effort rendering; a missing or corrupt sync state
        degrades to "no record" notes — this never crashes and never raises.

        Evidence budgets: `max_chunks` caps the rows per response (default
        50, hard cap 50), `max_tokens` is an approximate output budget, and
        `continuation_token` pages through long chains.

        Returns the chain: concept → `sources[]` entries → source
        file/digest, then footnote references → definitions. A missing
        concept returns a clean "not found" error.
        """
        concept = self.bundle.get(concept_id) if isinstance(concept_id, str) else None
        if concept is None:
            return (
                f"Error: concept {concept_id!r} not found in this bundle. "
                "Use `list` to see all concept ids or `search` to find one "
                "by keyword."
            )
        ingested = self._ingested_sources(concept.id)
        sources = _coerce_sources(concept.frontmatter)
        definitions = _footnote_definitions(concept.body)
        refs = _footnote_refs(concept.body)
        try:
            rel_path = concept.path.relative_to(self.bundle.root).as_posix()
        except (ValueError, OSError):
            rel_path = concept.path.name

        units = [
            _concept_label(concept),
            f"_Path: `{rel_path}` · body sha256: `{_concept_sha256(concept)[:16]}…`_",
        ]
        temporal_note = self._temporal_note(concept, _temporal.utcnow())
        if temporal_note:
            units.append(f"_Temporal status: {temporal_note}._")
        units.append(f"## Sources ({len(sources)})")
        if sources:
            for entry in sources:
                units.append(f"- {_render_source_entry(entry)}")
                if ingested:
                    for src_path, sha in ingested:
                        digest = f" (sha256: `{sha[:16]}…`)" if sha else ""
                        units.append(f"  → ingested from `{src_path}`{digest}")
                else:
                    units.append(
                        "  → _no sync-state record links this concept to an "
                        "ingested source_"
                    )
        else:
            units.append("_No `sources[]` entries in frontmatter._")
        units.append(f"## Footnote references ({len(refs)})")
        if refs:
            for label in refs:
                definition = definitions.get(label)
                if definition:
                    units.append(f"- [^{label}]: {definition}")
                else:
                    units.append(f"- [^{label}]: _definition not found in body_")
        else:
            units.append("_No footnote references in body._")

        title = f"Provenance for {concept_id}"
        return self._render_paged(
            title=title,
            whole=f"# {title}\n\n" + "\n".join(units),
            units=units,
            max_chunks=max_chunks,
            chunk_default=50,
            max_tokens=max_tokens,
            continuation_token=continuation_token,
        )

    # -- bundle diff ---------------------------------------------------------
    def diff(
        self,
        against: str | None = None,
        max_chunks: int = 50,
        max_tokens: int | None = None,
        continuation_token: str | None = None,
    ) -> str:
        """Diff this bundle against a previous state: added/removed/changed concepts.

        Two modes. With `against=<path to a bundle directory>`, compares the
        bound bundle ("current") against that directory ("previous"):
        added = ids only in current, removed = ids only in previous,
        changed = same id with a different body SHA-256 (or a different
        title). Each entry reports id, title, and the body sha256.

        Without `against`, falls back to the `sync-state.json` snapshot
        (`<bundle>/.okfsmith/sync-state.json`) when one exists: added/removed
        come from the snapshot's recorded concept ids, and "changed" marks
        concepts whose recorded source file's current SHA-256 differs from
        the snapshot (best-effort; URL and missing sources are skipped).
        With neither an `against` directory nor a usable snapshot, returns a
        clean error explaining how to call it.

        Evidence budgets: `max_chunks` caps the rows per response (default
        50, hard cap 50), `max_tokens` is an approximate output budget, and
        `continuation_token` pages through large diffs. Read-only: nothing
        here modifies either bundle. A bad `against` value returns a clean
        error, never a traceback.
        """
        if against is None:
            return self._diff_against_sync_state(
                max_chunks, max_tokens, continuation_token
            )
        if not isinstance(against, (str, Path)) or not str(against).strip():
            return "Error: `against` must be a path to a bundle directory."
        other_root = Path(str(against).strip())
        if not other_root.is_dir():
            return f"Error: `against` is not a directory: {against!r}."
        try:
            other = Bundle.load(other_root)
        except Exception as exc:
            return f"Error: could not load bundle at {against!r}: {exc}."
        current = {c.id: c for c in self.bundle.iter_concepts()}
        previous = {c.id: c for c in other.iter_concepts()}
        added = sorted(set(current) - set(previous))
        removed = sorted(set(previous) - set(current))
        changed = sorted(
            cid
            for cid in set(current) & set(previous)
            if _concept_sha256(current[cid]) != _concept_sha256(previous[cid])
            or _concept_title(current[cid]) != _concept_title(previous[cid])
        )

        units = [f"## Added ({len(added)})"]
        for cid in added:
            node = current[cid]
            units.append(
                f"- **{cid}** — {_concept_title(node)} — "
                f"sha256 `{_concept_sha256(node)[:12]}…`"
            )
        if not added:
            units.append("_none_")
        units.append(f"## Removed ({len(removed)})")
        for cid in removed:
            node = previous[cid]
            units.append(
                f"- **{cid}** — {_concept_title(node)} — "
                f"sha256 `{_concept_sha256(node)[:12]}…`"
            )
        if not removed:
            units.append("_none_")
        units.append(f"## Changed ({len(changed)})")
        for cid in changed:
            old, new = previous[cid], current[cid]
            units.append(
                f"- **{cid}** — {_concept_title(new)} — "
                f"`{_concept_sha256(old)[:12]}…` → `{_concept_sha256(new)[:12]}…`"
            )
        if not changed:
            units.append("_none_")

        notes = [f"_Comparing the current bundle against `{other_root}`._"]
        title = "Bundle diff"
        return self._render_paged(
            title=title,
            whole=f"# {title}\n\n" + "\n".join(notes) + "\n\n" + "\n".join(units),
            units=units,
            notes=notes,
            max_chunks=max_chunks,
            chunk_default=50,
            max_tokens=max_tokens,
            continuation_token=continuation_token,
        )

    def _diff_against_sync_state(
        self, max_chunks: Any, max_tokens: Any, continuation_token: Any
    ) -> str:
        """``diff()`` with no ``against``: compare against the sync snapshot."""
        state = _load_sync_state(self.bundle)
        if state is None:
            return (
                "Error: no `against` bundle directory given and no usable "
                "`sync-state.json` snapshot found in this bundle (looked for "
                "`<bundle>/.okfsmith/sync-state.json`). Pass "
                "`against=<path to a bundle directory>` to compare against it."
            )
        origins: dict[str, list[tuple[str, str | None]]] = {}
        records = state.get("sources")
        record_count = 0
        if isinstance(records, dict):
            record_count = len(records)
            for key, record in records.items():
                if not isinstance(record, dict):
                    continue
                path = _decode_state_key(key)
                sha = record.get("sha256")
                sha = sha if isinstance(sha, str) else None
                raw_concepts = record.get("concepts")
                ids = (
                    [str(cid) for cid in raw_concepts]
                    if isinstance(raw_concepts, (list, tuple))
                    else []
                )
                for cid in ids:
                    origins.setdefault(cid, []).append((path, sha))
        current = {c.id: c for c in self.bundle.iter_concepts()}
        prev_ids = set(origins)
        added = sorted(set(current) - prev_ids)
        removed = sorted(prev_ids - set(current))
        changed: list[tuple[str, str, str, str]] = []
        for cid in sorted(set(current) & prev_ids):
            for path, old_sha in origins[cid]:
                if not old_sha:
                    continue
                candidate = Path(path)
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                new_sha = _sha256_file(candidate)
                if new_sha and new_sha != old_sha:
                    changed.append((cid, path, old_sha, new_sha))
                    break

        units = [f"## Added ({len(added)})"]
        for cid in added:
            node = current[cid]
            units.append(
                f"- **{cid}** — {_concept_title(node)} — "
                f"sha256 `{_concept_sha256(node)[:12]}…`"
            )
        if not added:
            units.append("_none_")
        units.append(f"## Removed ({len(removed)})")
        units.extend(f"- **{cid}**" for cid in removed)
        if not removed:
            units.append("_none_")
        units.append(f"## Changed ({len(changed)})")
        for cid, path, old_sha, new_sha in changed:
            units.append(
                f"- **{cid}** — {_concept_title(current[cid])} — "
                f"source `{path}` changed "
                f"(`{old_sha[:12]}…` → `{new_sha[:12]}…`)"
            )
        if not changed:
            units.append("_none_")

        notes = [
            "_Comparing against the `sync-state.json` snapshot "
            f"({record_count} source record(s))._"
        ]
        title = "Bundle diff"
        return self._render_paged(
            title=title,
            whole=f"# {title}\n\n" + "\n".join(notes) + "\n\n" + "\n".join(units),
            units=units,
            notes=notes,
            max_chunks=max_chunks,
            chunk_default=50,
            max_tokens=max_tokens,
            continuation_token=continuation_token,
        )


def build_server(bundle_path: str | Path):
    """Build (but do not start) the MCP server for the bundle at *bundle_path*.

    The bundle is loaded **once**, right here at startup — every tool call
    afterwards reads from the same in-memory :class:`Bundle`. Raises
    ``RuntimeError`` with an install hint if the ``mcp`` extra is missing,
    :class:`FileNotFoundError` if *bundle_path* does not exist,
    :class:`ValueError` if *bundle_path* is empty, and
    :class:`NotADirectoryError` if *bundle_path* is not a directory.

    The returned server is a FastMCP instance with the eight read-only tools
    registered: ``index``, ``list``, ``search``, ``get``, ``neighbors``,
    ``traverse``, ``provenance``, ``diff``.
    """
    if str(bundle_path).strip() == "":
        raise ValueError("bundle_path must not be empty")
    root = Path(bundle_path)
    if not root.exists():
        raise FileNotFoundError(f"Bundle not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Bundle path is not a directory: {root}")
    bundle = Bundle.load(root)
    FastMCP = _require_fastmcp()
    server = FastMCP("okfsmith")
    tools = BundleTools(bundle)
    server.tool(tools.index)
    server.tool(tools.list)
    server.tool(tools.search)
    server.tool(tools.get)
    server.tool(tools.neighbors)
    server.tool(tools.traverse)
    server.tool(tools.provenance)
    server.tool(tools.diff)
    return server


def serve(bundle_path: str | Path, transport: str = "stdio") -> None:
    """Serve the bundle at *bundle_path* over the given MCP transport.

    ``transport`` defaults to ``"stdio"`` (the standard way MCP clients
    launch servers). Other FastMCP transports such as ``"sse"`` or
    ``"streamable-http"`` may be passed through.
    """
    server = build_server(bundle_path)
    server.run(transport=transport)
