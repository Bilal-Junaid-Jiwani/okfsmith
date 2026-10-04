"""Markdown link extraction and concept-link graph helpers.

Used by the ``okfsmith graph`` command. Mirrors the link-resolution rules in
``.contract/spec_decisions.md`` (W001/W002) without implementing validation
itself: a link target is dead when neither ``<target>`` nor ``<target>.md``
resolves to a file in the bundle (fragments/queries stripped, external URLs
skipped); a concept is an orphan when no ``index.md`` link entry reaches it,
directly or via a directory entry.

Section-concept fallback: links written in a per-section concept (id
``doc/section``) are relative to the source *document*, so when the plain
file-path resolution misses, :func:`resolve_link` (given the bundle's concept
ids) walks up the linking concept's id and — when the target names a whole
document that was split into per-section concepts — resolves to that
document's primary section concept (see :func:`primary_section_id`).
Genuinely broken links stay dead. This is the same rule the dashboard's
Explore graph applies, so ``okfsmith graph``, the dashboard graph, and the
W001 validator agree.
"""

from __future__ import annotations

import re
from collections.abc import Callable
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


def primary_section_id(
    concept_ids: set[str],
    doc_id: str,
    gen_at: Callable[[str], str] | None = None,
) -> str | None:
    """Return the primary concept id for a whole-document link target.

    When a markdown link points at a document (``other.md``) that was split
    into per-section concepts (``other/<section>``), the edge targets the
    document's primary concept: the section whose slug matches the file stem,
    else the earliest-generated section, else the first id alphabetically.
    ``gen_at`` maps a concept id to its ``generated.at`` timestamp string
    (missing/unknown sorts first — same as an empty timestamp).
    Returns ``None`` when no concept belongs to that document.
    """
    prefix = doc_id + "/"
    cands = [i for i in concept_ids if i.startswith(prefix)]
    if not cands:
        return None
    stem = doc_id.rsplit("/", 1)[-1]
    for i in cands:
        if i.rsplit("/", 1)[-1] == stem:
            return i
    key = (lambda i: (gen_at(i), i)) if gen_at is not None else (lambda i: ("", i))
    return sorted(cands, key=key)[0]


def _resolve_id_target(concept_id: str, raw: str) -> str | None:
    """Resolve a raw markdown link target to a concept id, or ``None``.

    Id-space twin of the file-path resolution in :func:`resolve_link`:
    external URIs (any scheme) and pure ``#fragment`` links are not concept
    links; ``/a/b`` is bundle-absolute; anything else resolves relative to
    the linking concept's directory; a trailing ``.md`` suffix, query strings
    and fragments are stripped; ``.``/``..`` segments collapse (never above
    the bundle root).
    """
    raw = (raw or "").strip().strip("<>")
    if not raw or raw.startswith("#"):
        return None
    if _EXTERNAL_RE.match(raw):
        return None  # external resource — not a concept link
    target = re.split(r"[#?]", raw, maxsplit=1)[0].strip()
    if not target:
        return None
    if target.startswith("/"):
        target = target[1:]
    else:
        base = concept_id.rpartition("/")[0]
        target = f"{base}/{target}" if base else target
    parts: list[str] = []
    for part in target.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    target = "/".join(parts)
    if target.lower().endswith(".md"):
        target = target[: -len(".md")]
    return target or None


def _section_concept_fallback(
    root: Path,
    source_path: Path,
    clean: str,
    concept_ids: set[str],
    gen_at: Callable[[str], str] | None,
) -> str | None:
    """Walk-up + primary-section resolution for section-concept links.

    The link is written relative to the source *document*, but the linking
    concept may be a section of that document (id like ``doc/section``), so
    a miss at the concept's own level is retried at each ancestor level.
    When the target names a whole document split into per-section concepts,
    the target document's primary section concept id is returned.
    Returns ``None`` when nothing resolves.
    """
    try:
        rel = source_path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    source_id = rel.with_suffix("").as_posix() if rel.suffix.lower() == ".md" else rel.as_posix()
    target = _resolve_id_target(source_id, clean)
    if not target or target == source_id:
        return None
    if target in concept_ids:
        return target
    base = source_id
    while "/" in base:
        base = base.rpartition("/")[0]
        cand = _resolve_id_target(base, clean)
        if not cand or cand == source_id:
            continue
        if cand in concept_ids:
            return cand
        primary = primary_section_id(concept_ids, cand, gen_at)
        if primary and primary != source_id:
            return primary
    return None


def resolve_link(
    root: Path,
    source_path: Path,
    target: str,
    *,
    concept_ids: set[str] | None = None,
    gen_at: Callable[[str], str] | None = None,
) -> tuple[str, str | None]:
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

    When *concept_ids* is given (the bundle's concept id set) and the
    file-path resolution misses *inside* the bundle, the section-concept
    fallback runs: links written in a per-section concept are retried
    relative to the source document, and a target naming a whole document
    split into per-section concepts resolves to its primary section
    (:func:`primary_section_id`). Targets escaping the bundle root stay
    dead — the fallback never runs for them.
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
    if concept_ids is not None:
        fallback = _section_concept_fallback(root, source_path, clean, concept_ids, gen_at)
        if fallback is not None:
            return "ok", fallback
    return "dead", None


def _node_for(bundle: Bundle, concept_id: str) -> dict:
    concept = bundle.get(concept_id)
    fm = concept.frontmatter if concept else {}
    title = fm.get("title") or concept_id
    return {"id": concept_id, "type": str(fm.get("type") or ""), "title": str(title)}


def _gen_at_of(frontmatter: dict | None) -> str:
    """Extract the ``generated.at`` timestamp string from frontmatter."""
    fm = frontmatter or {}
    return str((fm.get("generated") or {}).get("at") or "")


def build_graph(bundle: Bundle) -> dict:
    """Build the concept link graph.

    Returns ``{"nodes": [...], "edges": [...], "dead_links": [...]}`` where
    nodes carry ``id``/``type``/``title``, edges are ``{"from", "to"}`` dicts,
    and dead links are ``{"source", "target"}`` dicts (raw target text).
    Asset and reserved-file links are skipped silently: they are neither
    edges nor dead links.

    Links written in per-section concepts resolve relative to the source
    document (section-concept fallback): a target naming a whole document
    split into sections links to that document's primary section concept.
    """
    concepts = list(bundle.iter_concepts())
    nodes = {c.id: _node_for(bundle, c.id) for c in concepts}
    concept_ids = set(nodes)
    by_id = {c.id: c for c in concepts}

    def _gen_at(cid: str) -> str:
        return _gen_at_of(by_id[cid].frontmatter)

    edges: list[dict] = []
    dead_links: list[dict] = []
    seen_edges: set[tuple[str, str]] = set()
    for concept in concepts:
        for target in extract_link_targets(concept.body):
            kind, concept_id = resolve_link(
                bundle.root, concept.path, target, concept_ids=concept_ids, gen_at=_gen_at
            )
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
    """Concept ids not reachable from any ``index.md`` link entry.

    Whole-document link entries resolve through the same section-concept
    fallback as :func:`build_graph`: an entry naming a document split into
    per-section concepts reaches that document's primary section.
    """
    concepts = list(bundle.iter_concepts())
    concept_ids = {c.id for c in concepts}
    by_id = {c.id: c for c in concepts}

    def _gen_at(cid: str) -> str:
        return _gen_at_of(by_id[cid].frontmatter)

    indexed: set[str] = set()
    for index_path in sorted(bundle.root.rglob("index.md")):
        try:
            text = index_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # QA L8: a non-UTF-8 nested index.md must not crash the graph.
            continue
        for target in extract_link_targets(text):
            kind, concept_id = resolve_link(
                bundle.root, index_path, target, concept_ids=concept_ids, gen_at=_gen_at
            )
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
