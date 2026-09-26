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

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from okfsmith.core import frontmatter as _fm
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
    """The five MCP tool functions, bound to one loaded bundle.

    Instances are created by :func:`build_server`; each method is registered
    as an MCP tool. They are also directly callable (as the tests do), with
    no MCP transport required.

    Every method returns compact markdown text. Lookup failures return a
    plain-English ``Error: ...`` string — never an exception — so agents get
    a recoverable message instead of a tool crash.
    """

    def __init__(self, bundle: Bundle) -> None:
        self.bundle = bundle

    # -- progressive disclosure entry point ---------------------------------
    def index(self) -> str:
        """Return the bundle's root index.md — the map of the whole knowledge base.

        This is the starting point for progressive disclosure: the index
        lists every concept with a one-line summary. Read this first to
        orient yourself, then use `search` to find concepts by keyword and
        `get` to read a concept in full. Each index entry's concept id can
        be passed to `get`, `neighbors`, or `list` for deeper exploration.

        Returns the raw index.md text; if the bundle has no index.md, says
        so and suggests `list` instead.
        """
        if not self.bundle.index_text:
            return (
                "This bundle has no root index.md. Use the `list` tool to see "
                "all concepts, or `search` to find one by keyword."
            )
        return self.bundle.index_text

    # -- inventory -----------------------------------------------------------
    def list(self, filter_type: str = "", limit: int = 50) -> str:
        """List every concept in the bundle: id, type, trust tier, and title.

        Use this for a full inventory of the knowledge base, or to narrow
        down by concept type. `filter_type` matches the concept's frontmatter
        `type` (case-insensitive substring, e.g. "Metric", "Playbook",
        "Attested Computation"). `limit` caps the number of rows returned
        (non-numeric input falls back to the default 50).

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
        lines = [_concept_label(c) for c in concepts]
        return f"# Concepts ({len(lines)})\n\n" + "\n".join(f"- {line}" for line in lines)

    # -- keyword search ------------------------------------------------------
    def search(self, query: str, limit: int = 10) -> str:
        """Search concepts by id, title, description, tags, and body text.

        Full-text BM25 ranking (stdlib-only ``okfsmith.search`` engine,
        shared with the ``okfsmith search`` CLI and the chat REPL so all
        three rank identically): field weights id/title ×3,
        description/tags ×2, body ×1, with stemming, quoted phrases, and
        ``-exclusions``. `limit` caps the number of results (default 10;
        non-numeric input falls back to 10).

        Returns a compact markdown list: concept id, type, trust tier
        (`human-reviewed` > `machine-confirmed` > `unverified`), title, and
        a one-line description. Use `get` with a result's id to read the
        full concept. A missing or blank query returns a clean error,
        never an exception.
        """
        if not isinstance(query, str) or not query.split():
            return "Error: `query` is empty — provide a keyword to search for."
        limit = _coerce_limit(limit, 10)
        hits = rank_concepts(self.bundle, query, limit)
        if not hits:
            return f"No concepts match {query!r}. Try broader keywords or use `list`."
        lines = [
            f"{_concept_label(c)}\n  {_description(c)}" for _, c in hits
        ]
        return f"# Search: {query} ({len(lines)} result(s))\n\n" + "\n".join(
            f"- {line}" for line in lines
        )

    # -- full concept --------------------------------------------------------
    def get(self, concept_id: str) -> str:
        """Read one concept in full: its YAML frontmatter followed by its markdown body.

        `concept_id` is the concept's path id, e.g. "finance/revenue" (see
        `list` or `search` for valid ids). The frontmatter carries the OKF
        metadata — `type`, `title`, `description`, `tags`, trust info
        (`generated` / `verified`), and `sources` — and the body is the
        knowledge content itself.

        Returns the concept document (frontmatter + body). If the id does
        not exist, returns a clean "not found" error suggesting how to find
        valid ids.
        """
        concept = self.bundle.get(concept_id)
        if concept is None:
            return (
                f"Error: concept {concept_id!r} not found in this bundle. "
                "Use `list` to see all concept ids or `search` to find one "
                "by keyword."
            )
        return _fm.serialize_frontmatter(concept.frontmatter, concept.body)

    # -- link graph ----------------------------------------------------------
    def neighbors(self, concept_id: str) -> str:
        """Show a concept's outgoing links and incoming backlinks.

        Outgoing links are the markdown links in the concept's own body.
        Incoming links (backlinks) are found by scanning every other
        concept's body for links pointing at this concept. Each link is
        shown with its id, type, and the link text — which is the
        prose-derived description of the relation (e.g. "computed by [the
        revenue computation](/computations/revenue)").

        Returns two sections, "Outgoing" and "Incoming". A missing concept
        returns a clean "not found" error.
        """
        concept = self.bundle.get(concept_id)
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

        parts = [f"# Links for {concept_id}"]
        parts.append(f"\n## Outgoing ({len(outgoing)})")
        parts.append(
            "\n".join(_fmt_out(lid, text) for lid, text in outgoing)
            if outgoing
            else "_No outgoing links._"
        )
        parts.append(f"\n## Incoming ({len(incoming)})")
        parts.append(
            "\n".join(_fmt_in(sid, stype, text) for sid, stype, text in incoming)
            if incoming
            else "_No incoming links._"
        )
        return "\n".join(parts)


def build_server(bundle_path: str | Path):
    """Build (but do not start) the MCP server for the bundle at *bundle_path*.

    The bundle is loaded **once**, right here at startup — every tool call
    afterwards reads from the same in-memory :class:`Bundle`. Raises
    ``RuntimeError`` with an install hint if the ``mcp`` extra is missing,
    :class:`FileNotFoundError` if *bundle_path* does not exist,
    :class:`ValueError` if *bundle_path* is empty, and
    :class:`NotADirectoryError` if *bundle_path* is not a directory.

    The returned server is a FastMCP instance with the five read-only tools
    registered: ``index``, ``list``, ``search``, ``get``, ``neighbors``.
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
    return server


def serve(bundle_path: str | Path, transport: str = "stdio") -> None:
    """Serve the bundle at *bundle_path* over the given MCP transport.

    ``transport`` defaults to ``"stdio"`` (the standard way MCP clients
    launch servers). Other FastMCP transports such as ``"sse"`` or
    ``"streamable-http"`` may be passed through.
    """
    server = build_server(bundle_path)
    server.run(transport=transport)
