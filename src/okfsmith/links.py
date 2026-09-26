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

#: Inline markdown links, excluding image links (``![alt](src)``).
_LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

#: Matches URI schemes (``https:``, ``mailto:``) and other external targets.
_EXTERNAL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def extract_link_targets(body: str) -> list[str]:
    """Return raw link targets from markdown *body*, in order, de-duplicated."""
    seen: list[str] = []
    for match in _LINK_RE.finditer(body or ""):
        target = match.group(2).strip()
        if target and target not in seen:
            seen.append(target)
    return seen


def _strip_fragment_query(target: str) -> str:
    return target.split("#", 1)[0].split("?", 1)[0].strip()


def resolve_link(root: Path, source_path: Path, target: str) -> tuple[str, str | None]:
    """Resolve a raw markdown link *target* against the bundle.

    Returns ``(kind, concept_id)`` where *kind* is one of:

    - ``"external"`` — URI scheme or pure fragment; not bundle content.
    - ``"ok"`` — resolves to a concept document; *concept_id* is its id.
    - ``"dir"`` — resolves to a directory (index directory entry).
    - ``"dead"`` — resolves to nothing in the bundle.
    """
    clean = _strip_fragment_query(target)
    if not clean or clean.startswith("#") or _EXTERNAL_RE.match(clean):
        return "external", None
    base = root / clean.lstrip("/") if clean.startswith("/") else source_path.parent / clean
    # Security (audit-3 finding 1): links may walk up out of the bundle
    # (e.g. ``[x](../../evil.md)``). Resolve and contain: anything outside
    # the bundle root is dead, never a ValueError crash (DoS) and never an
    # existence oracle for host files.
    try:
        resolved_base = base.resolve()
    except OSError:
        return "dead", None
    try:
        resolved_base.relative_to(root)
    except ValueError:
        return "dead", None
    candidates = [resolved_base, resolved_base.parent / (resolved_base.name + ".md")]
    for candidate in candidates:
        if candidate.is_file():
            if candidate.suffix.lower() == ".md":
                rel = candidate.relative_to(root)
                return "ok", rel.with_suffix("").as_posix()
            return "dead", None
        if candidate.is_dir():
            return "dir", None
    if resolved_base.is_dir():
        return "dir", None
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
    """
    nodes = {c.id: _node_for(bundle, c.id) for c in bundle.iter_concepts()}
    edges: list[dict] = []
    dead_links: list[dict] = []
    seen_edges: set[tuple[str, str]] = set()
    for concept in bundle.iter_concepts():
        for target in extract_link_targets(concept.body):
            kind, concept_id = resolve_link(bundle.root, concept.path, target)
            if kind == "external" or kind == "dir":
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
        except OSError:
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


def mermaid_flowchart(graph: dict) -> str:
    """Render the graph as a Mermaid ``flowchart``."""
    def node_id(concept_id: str) -> str:
        return re.sub(r"[^A-Za-z0-9_]", "_", concept_id)

    lines = ["flowchart LR"]
    for node in graph["nodes"]:
        label = f'{node["id"]} — {node["title"]}'.replace('"', "'").replace("]", ")")
        lines.append(f'    {node_id(node["id"])}["{label}"]')
    for edge in graph["edges"]:
        lines.append(f'    {node_id(edge["from"])} --> {node_id(edge["to"])}')
    return "\n".join(lines) + "\n"
