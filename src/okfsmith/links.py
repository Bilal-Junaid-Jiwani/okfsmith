"""Markdown link extraction and concept-link graph helpers.

Used by the ``okfsmith graph`` command. Mirrors the link-resolution rules in
``.contract/spec_decisions.md`` (W001/W002) without implementing validation
itself: a link target is dead when neither ``<target>`` nor ``<target>.md``
resolves to a file in the bundle (fragments/queries stripped, external URLs
skipped); a concept is an orphan when no ``index.md`` link entry reaches it,
directly or via a directory entry.
"""

from __future__ import annotations

import re
from pathlib import Path

from okfsmith.core.bundle import Bundle
from okfsmith.core.spec import RESERVED_FILES

#: Inline markdown links, excluding image links (``![alt](src)``).
#:
#: ReDoS-hardened (QA H3): every "scan to a delimiter" character class excludes
#: that delimiter's opener, so a failed match attempt gives up after O(1) extra
#: characters instead of scanning to end-of-input. The old pattern's
#: ``[^\\]]*`` label and ``[^)\\s]+`` target groups were quadratic on crafted
#: input (``[`` x 40000 took ~13 s; ``[a](`` x 20000 took ~130 s). The label
#: group excludes ``[`` (nested ``[[a](b.md)](c.md)`` still extracts ``b.md``
#: via the inner match) and the paren-content group excludes ``(``.
#: Targets may contain spaces (QA L4); an optional CommonMark ``"title"`` (or
#: ``'title'``) suffix is stripped in :func:`extract_link_targets`.
_LINK_RE = re.compile(
    r"(?<!!)"  # not an image link
    r"\[([^\[\]]*)\]"  # link label: may span lines, no nested brackets
    r"\("  # opening paren (must directly follow "]", per CommonMark)
    r"([^()\n]*)"  # raw paren content: target + optional title, no parens
    r"\)"
)

#: Matches URI schemes (``https:``, ``mailto:``) and other external targets.
_EXTERNAL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")

#: Trailing CommonMark title suffix (``"..."`` or ``'...'``) stripped from the
#: raw paren content to recover the bare link target (QA M12).
_TITLE_SUFFIX_RE = re.compile(r"""\s+("[^"]*"|'[^']*')\s*$""")

#: Maximum body length scanned for links. A hard cap (QA H3) so multi-megabyte
#: bodies cannot be used for CPU-exhaustion DoS; links past the cap are not
#: extracted.
_MAX_LINK_SCAN_LEN = 1_000_000


def extract_link_targets(body: str) -> list[str]:
    """Return raw link targets from markdown *body*, in order, de-duplicated.

    This is the single shared link-extraction implementation, also used by the
    validator (which must not define its own link regex). Supports CommonMark
    inline links: bare targets (spaces allowed, QA L4), ``<angle-wrapped>``
    targets, and an optional ``"title"``/``'title'`` suffix (stripped).
    Bodies longer than 1 MiB are truncated before scanning (DoS guard, QA H3).
    """
    seen: list[str] = []
    seen_set: set[str] = set()
    for match in _LINK_RE.finditer((body or "")[:_MAX_LINK_SCAN_LEN]):
        content = match.group(2)
        # Strip an optional trailing CommonMark title: `[t](b.md "The B")`.
        title_match = _TITLE_SUFFIX_RE.search(content)
        if title_match:
            content = content[: title_match.start()]
        # Angle-wrapped targets: `[t](<my doc.md>)` (QA L4).
        content = content.strip()
        if content.startswith("<") and content.endswith(">") and len(content) >= 2:
            content = content[1:-1].strip()
        if content and content not in seen_set:
            seen_set.add(content)
            seen.append(content)
    return seen


def _strip_fragment_query(target: str) -> str:
    return target.split("#", 1)[0].split("?", 1)[0].strip()


def resolve_link(root: Path, source_path: Path, target: str) -> tuple[str, str | None]:
    """Resolve a raw markdown link *target* against the bundle.

    Returns ``(kind, concept_id)`` where *kind* is one of:

    - ``"external"`` — URI scheme, protocol-relative ``//host`` (QA L6), or
      pure fragment; not bundle content.
    - ``"ok"`` — resolves to a concept document; *concept_id* is its id.
    - ``"dir"`` — resolves to a directory (index directory entry).
    - ``"asset"`` — resolves to an existing non-markdown file (QA M14); not
      dead, but not a concept either (no graph edge, no dead-link entry).
    - ``"reserved"`` — resolves to a reserved bundle file (``index.md`` /
      ``log.md``, any casing); not a concept, never reported dead (QA L9).
    - ``"dead"`` — resolves to nothing in the bundle. Null bytes (QA H14) and
      filesystem errors (QA L7) also resolve here instead of raising.
    """
    clean = _strip_fragment_query(target)
    # QA L6: protocol-relative links are external, matching the validator.
    if not clean or clean.startswith("#") or clean.startswith("//") or _EXTERNAL_RE.match(clean):
        return "external", None
    base = root / clean.lstrip("/") if clean.startswith("/") else source_path.parent / clean
    # Security (audit-3 finding 1): links may walk up out of the bundle
    # (e.g. ``[x](../../evil.md)``). Resolve and contain: anything outside
    # the bundle root is dead, never a ValueError crash (DoS) and never an
    # existence oracle for host files.
    try:
        resolved_base = base.resolve()
    except (OSError, ValueError):
        # QA H14: null bytes raise ValueError ("embedded null byte").
        return "dead", None
    try:
        resolved_base.relative_to(root)
    except ValueError:
        return "dead", None
    # QA L9: reserved bundle files are never concepts, but linking them is
    # not a dead link.
    if resolved_base.name.lower() in RESERVED_FILES:
        return "reserved", None
    candidates = [resolved_base, resolved_base.parent / (resolved_base.name + ".md")]
    try:
        for candidate in candidates:
            if candidate.is_file():
                if candidate.suffix.lower() == ".md":
                    rel = candidate.relative_to(root)
                    return "ok", rel.with_suffix("").as_posix()
                # QA M14: an existing non-markdown file is an asset, not dead.
                return "asset", None
            if candidate.is_dir():
                return "dir", None
        if resolved_base.is_dir():
            return "dir", None
    except (OSError, ValueError):
        # QA L7: over-long targets raise OSError (ENAMETOOLONG) from is_file().
        return "dead", None
    return "dead", None


def _node_for(bundle: Bundle, concept_id: str) -> dict:
    concept = bundle.get(concept_id)
    fm = concept.frontmatter if concept else {}
    title = fm.get("title") or concept_id
    return {"id": concept_id, "type": str(fm.get("type") or ""), "title": str(title)}


def build_graph(bundle: Bundle) -> dict:
    """Build the concept link graph.

    Returns ``{"nodes": [...], "edges": [...], "dead_links": [...]}`` where
    nodes carry ``id``/``type``/``title``, edges are ``{"from", "to"}`` dicts,
    and dead links are ``{"source", "target"}`` dicts (raw target text).
    Asset and reserved-file links are skipped silently: they are neither
    edges nor dead links.
    """
    nodes = {c.id: _node_for(bundle, c.id) for c in bundle.iter_concepts()}
    edges: list[dict] = []
    dead_links: list[dict] = []
    seen_edges: set[tuple[str, str]] = set()
    for concept in bundle.iter_concepts():
        for target in extract_link_targets(concept.body):
            kind, concept_id = resolve_link(bundle.root, concept.path, target)
            if kind in ("external", "dir", "asset", "reserved"):
                continue
            if kind == "ok" and concept_id in nodes:
                key = (concept.id, concept_id)
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append({"from": concept.id, "to": concept_id})
            else:
                dead_links.append({"source": concept.id, "target": target})
    return {"nodes": list(nodes.values()), "edges": edges, "dead_links": dead_links}


def orphans(bundle: Bundle) -> list[str]:
    """Concept ids not reachable from any ``index.md`` link entry."""
    indexed: set[str] = set()
    for index_path in sorted(bundle.root.rglob("index.md")):
        try:
            text = index_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # QA L8: a non-UTF-8 nested index.md must not crash the graph.
            continue
        for target in extract_link_targets(text):
            kind, concept_id = resolve_link(bundle.root, index_path, target)
            if kind == "ok" and concept_id:
                indexed.add(concept_id)
            elif kind == "dir":
                # A directory entry reaches every concept beneath it.
                clean = _strip_fragment_query(target).lstrip("/")
                try:
                    prefix = (index_path.parent / clean).resolve().relative_to(
                        bundle.root
                    ).as_posix()
                except (ValueError, OSError):
                    continue
                for concept in bundle.iter_concepts():
                    if concept.id == prefix or concept.id.startswith(prefix + "/"):
                        indexed.add(concept.id)
    return sorted(c.id for c in bundle.iter_concepts() if c.id not in indexed)


def _node_id(concept_id: str) -> str:
    """Collision-free Mermaid node id for a concept id (QA M15).

    The mapping is injective: ``_`` is doubled first, then every remaining
    disallowed character becomes ``_u<codepoint>_``, so distinct concept ids
    (e.g. ``x/y`` vs ``x-y``, previously both ``x_y``) can never collide. The
    ``n_`` prefix keeps ids valid even when they start with a digit.
    """
    escaped = concept_id.replace("_", "__")
    escaped = re.sub(r"[^A-Za-z0-9_]", lambda m: f"_u{ord(m.group(0)):04x}_", escaped)
    return f"n_{escaped}" if escaped else "n_empty"


def mermaid_flowchart(graph: dict) -> str:
    """Render the graph as a Mermaid ``flowchart``.

    Dead links are included as ``%%`` comments (QA L2) so no information from
    ``graph --format text`` is lost in the mermaid rendering.
    """
    lines = ["flowchart LR"]
    for node in graph["nodes"]:
        label = f'{node["id"]} — {node["title"]}'.replace('"', "'").replace("]", ")")
        lines.append(f'    {_node_id(node["id"])}["{label}"]')
    for edge in graph["edges"]:
        lines.append(f'    {_node_id(edge["from"])} --> {_node_id(edge["to"])}')
    for item in graph.get("dead_links", []):
        source = str(item["source"]).replace("\n", " ")
        target = str(item["target"]).replace("\n", " ")
        lines.append(f"    %% dead link: {source} -> {target}")
    return "\n".join(lines) + "\n"
