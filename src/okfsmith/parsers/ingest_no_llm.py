"""--no-llm ingest: ParsedDocument -> DRAFT concepts, no LLM involved.

Emits one DRAFT concept per section with structure-only frontmatter.
Sources that are too small, failed to parse, or whose sections come only
from OCR-flagged pages produce no concepts (stub prevention); what would
need OCR is reported, never stubbed.

Each concept cites its source in frontmatter ``sources[]`` (the same shape
the LLM pipeline emits) and in ``source_digest`` when the caller supplies
the source file's SHA-256. Descriptions are derived from each section's
own text, and sibling sections of the same document are linked with a
``## See also`` body section — sequence neighbours plus sections whose
title this section's text mentions — so the offline graph is not empty.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from okfsmith import __version__ as _PACKAGE_VERSION

from .sectioning import TOO_SMALL_CHARS

if TYPE_CHECKING:
    from okfsmith.core.bundle import Bundle

    from . import ParsedDocument

log = logging.getLogger(__name__)

# Stamped into every generated concept's ``generated.by``. Derived from the
# installed distribution (single source of truth: okfsmith.__version__), NOT
# a hardcoded literal — a stale "okfsmith/0.2.0" literal shipped until 0.8.4
# and mis-stamped every offline concept (external review finding, 0.8.5).
GENERATED_BY = f"okfsmith/{_PACKAGE_VERSION}"
# Fallback description for sections with no usable body text (e.g. a
# tables-only section). Sections WITH text get a content-derived
# description instead (see _derive_description).
DESCRIPTION = "Draft concept extracted without LLM; needs review"
BODY_MAX_CHARS = 8000

_DESCRIPTION_MAX_CHARS = 200
_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]+")
_LINK_MARKUP_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# Cap on derived See-also entries per concept: enough to connect a
# document's sections without turning long documents into link farms.
_MAX_SEE_ALSO = 8
# Title mentions shorter than this are too ambiguous to link on.
_MIN_MENTION_TITLE_CHARS = 4


def _truncate(text: str, limit: int = BODY_MAX_CHARS) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit("\n", 1)[0] or text[:limit]
    return cut.rstrip() + "\n\n[... truncated: section body exceeds no-LLM limit ...]"


def _derive_description(text: str) -> str:
    """Derive a section-specific description from the section's own text.

    Uses the first meaningful sentence; falls back to a trimmed opening
    excerpt when no sentence boundary is usable, and to the generic
    DESCRIPTION only when the section has no text at all. The result
    differs per section and reflects its content (the pre-0.8.5 behaviour
    stamped one identical line on every concept).
    """
    flat = " ".join((text or "").split())
    # Drop markdown link targets / emphasis markers so the description
    # reads as prose, not markup.
    flat = _LINK_MARKUP_RE.sub(r"\1", flat)
    flat = flat.replace("`", "").replace("**", "").replace("__", "")
    flat = flat.lstrip("#>*-+ ").strip()
    if not flat:
        return DESCRIPTION
    sentence = _SENTENCE_RE.search(flat)
    candidate = sentence.group(0).strip() if sentence else ""
    if len(candidate) < 20:
        candidate = flat
    if len(candidate) <= _DESCRIPTION_MAX_CHARS:
        return candidate
    cut = candidate[:_DESCRIPTION_MAX_CHARS].rsplit(" ", 1)[0].rstrip(",;:")
    return (cut or candidate[:_DESCRIPTION_MAX_CHARS].rstrip()) + "…"


def _safe_log_text(value: object) -> str:
    """Render *value* as text that always encodes as UTF-8.

    Source paths can contain undecodable bytes (surrogate escapes, M8);
    embedding them verbatim in a log message makes ``indexlog.append_log``
    raise ``UnicodeEncodeError`` when it writes ``log.md``. ``backslashreplace``
    keeps the name recognizable without ever failing to encode.
    """
    text = value if isinstance(value, str) else str(value)
    return text.encode("utf-8", errors="backslashreplace").decode("utf-8")


def _stored_concept_id(bundle: Bundle, concept_id: str) -> str:
    """Id under which ``write_concept`` will store *concept_id*.

    ``Bundle.write_concept`` slugifies each ``/``-separated segment to derive
    the on-disk path; the stored id is that path minus the suffix. Collision
    checks must run against this exact form (C3), not the raw candidate.
    """
    from okfsmith.core.bundle import concept_path_for

    return (
        concept_path_for(bundle.root, concept_id)
        .relative_to(bundle.root)
        .with_suffix("")
        .as_posix()
    )


def _alloc_concept_id(
    bundle: Bundle, stem: str, slug: str, used: set[str]
) -> tuple[str, str | None]:
    """Allocate a concept id for ``stem/slug`` that collides with nothing.

    Mirrors the LLM path's ``_concept_id_for`` (C3): the bundle is consulted
    via ``bundle.get()`` — not just the per-file ``used`` set — so two
    same-stem files in different directories can never silently overwrite
    each other's concepts. Appends ``-2``, ``-3``, … on collision and records
    the allocated (stored-form) id in ``used``.

    Returns ``(concept_id, superseded_id)``: when a ``-2``/``-3`` suffix was
    needed, ``superseded_id`` is the stored id of the displaced concept (so
    the caller can stamp ``supersedes``); otherwise ``None``.
    """
    base = f"{stem}/{slug}"
    base_stored = _stored_concept_id(bundle, base)
    candidate = base
    n = 2
    while True:
        stored = _stored_concept_id(bundle, candidate)
        if stored not in used and bundle.get(stored) is None:
            used.add(stored)
            superseded = base_stored if candidate != base else None
            return candidate, superseded
        candidate = f"{stem}/{slug}-{n}"
        n += 1


def _see_also_links(records: list[dict], doc_name: str) -> dict[int, list[tuple[str, str, str]]]:
    """Derive deterministic sibling links for one document's concepts.

    *records* are the pending concepts in section order, each with
    ``stored_id``/``title``/``text``. Returns ``{record_index: [(href,
    title, why), ...]}``. Two bases, both structural/textual — never
    invented:

    - sequence: the previous/next section of the same document;
    - mention: this section's text names another section's title
      (case-insensitive, word-bounded, titles >= 4 chars).

    Hrefs are the sibling's stored-id leaf segment: sibling concepts live
    in the same bundle directory, so the shared link resolution (relative
    to the linking concept's file) resolves them.
    """
    links: dict[int, list[tuple[str, str, str]]] = {i: [] for i in range(len(records))}

    def href(stored_id: str) -> str:
        return stored_id.rsplit("/", 1)[-1]

    mention_res: list[re.Pattern[str] | None] = []
    for rec in records:
        title = (rec["title"] or "").strip()
        if len(title) >= _MIN_MENTION_TITLE_CHARS:
            mention_res.append(
                re.compile(r"(?<!\w)" + re.escape(title) + r"(?!\w)", re.IGNORECASE)
            )
        else:
            mention_res.append(None)

    def add_link(
        out: list[tuple[str, str, str]], seen: set[str], j: int, why: str
    ) -> None:
        target = records[j]
        if target["stored_id"] in seen or len(out) >= _MAX_SEE_ALSO:
            return
        seen.add(target["stored_id"])
        out.append((href(target["stored_id"]), target["title"], why))

    for i, rec in enumerate(records):
        out: list[tuple[str, str, str]] = []
        seen: set[str] = set()

        # Mentions first (content-based, most informative), in document order.
        text = rec["text"] or ""
        if text:
            for j, pattern in enumerate(mention_res):
                if j != i and pattern is not None and pattern.search(text):
                    add_link(out, seen, j, "titled section mentioned in this section")
        if i + 1 < len(records):
            add_link(out, seen, i + 1, f"next section of {doc_name}")
        if i > 0:
            add_link(out, seen, i - 1, f"previous section of {doc_name}")
        links[i] = out
    return links


def _render_body(record: dict, links: list[tuple[str, str, str]]) -> str:
    body = _truncate(record["text"])
    if not links:
        return body
    lines = [body, "", "## See also", ""]
    for href, title, why in links:
        lines.append(f"- [{title}]({href}) — {why}")
    return "\n".join(lines).rstrip() + "\n"


def ingest_no_llm(
    bundle: Bundle,
    parsed: ParsedDocument,
    source_id: str,
    *,
    min_chars: int = TOO_SMALL_CHARS,
    digest: str | None = None,
) -> list[str]:
    """Ingest a ParsedDocument into *bundle* as DRAFT concepts.

    Returns the list of created concept ids. Creates nothing (returns [])
    when the source failed to parse, is too small to be meaningful, or has
    no parseable sections left after OCR-flagged pages are excluded.

    *min_chars* is the stub-prevention threshold (``--min-chars``);
    *digest*, when given, is the source file's SHA-256 and is recorded as
    frontmatter ``source_digest`` (the LLM path's field of the same name).
    """
    from okfsmith.core import indexlog
    from okfsmith.core.bundle import slugify, stamp_supersedes
    from okfsmith.core.spec import utc_now_iso

    from . import sectioning
    from .router import ocr_escalations

    # M8: source_id may hold undecodable bytes (surrogate escapes); never let
    # the raw value reach a log message or append_log (UnicodeEncodeError).
    safe_source = _safe_log_text(source_id)

    if (parsed.meta or {}).get("error"):
        log.warning("not ingesting %s: %s", safe_source, parsed.meta["error"])
        return []

    sectioned = sectioning.section(parsed, min_chars=min_chars)
    if sectioned.too_small:
        log.info(
            "deferring entity creation for %s: source under %d chars "
            "(stub prevention)",
            safe_source,
            min_chars,
        )
        return []

    ocr_pages = {
        pg.number for pg in (parsed.pages or []) if pg.needs_ocr
    }
    if ocr_pages:
        for msg in ocr_escalations(parsed):
            log.warning("ingest: %s", msg)

    stem = Path(source_id).stem or "document"
    doc_name = Path(source_id).name
    doc_title = (parsed.meta or {}).get("title") or doc_name
    used_ids: set[str] = set()

    # Phase 1: allocate ids and build frontmatter for every section that
    # will be written. Links are derived only among written concepts, so
    # allocation must finish before any body is rendered.
    records: list[dict] = []
    for i, sec in enumerate(sectioned.sections, start=1):
        span_pages = set(range(sec.page_span[0], sec.page_span[1] + 1))
        if span_pages and span_pages <= ocr_pages:
            # Entire section sits on OCR-flagged pages: report, don't stub.
            log.warning(
                "skipping section %r from %s: pages %s need OCR tier",
                sec.title,
                safe_source,
                sorted(span_pages),
            )
            continue
        if not (sec.text or "").strip() and not sec.tables:
            continue  # empty section: nothing to draft

        base = slugify(sec.title) if sec.title else ""
        slug = base or f"section-{i}"
        # C3: cross-document collision check via bundle.get(); never silently
        # overwrite an existing concept from a different source file.
        concept_id, superseded_id = _alloc_concept_id(bundle, stem, slug, used_ids)
        # sources[] mirrors the LLM pipeline's shape (§5.1: id + resource
        # REQUIRED): one entry citing this section's source document,
        # page-pinned when the section's span is known.
        if sec.page_span and sec.page_span[0] >= 1:
            resource_ref = f"{source_id}#page={sec.page_span[0]}"
        else:
            resource_ref = str(source_id)
        frontmatter = {
            "type": "Draft",
            "title": sec.title or f"Section {i} of {doc_name}",
            "description": _derive_description(sec.text),
            "resource": str(source_id),
            "sources": [
                {"id": "source-1", "resource": resource_ref, "title": doc_title}
            ],
            "generated": {"by": GENERATED_BY, "at": utc_now_iso()},
            "status": "draft",
            "tags": ["draft", "no-llm"],
        }
        if digest:
            frontmatter["source_digest"] = digest
        if superseded_id is not None and bundle.get(superseded_id) is not None:
            # Duplicate of an existing concept: record whom this replaces so
            # the temporal model demotes the stale version in retrieval.
            frontmatter = stamp_supersedes(frontmatter, superseded_id)
        records.append(
            {
                "concept_id": concept_id,
                "stored_id": _stored_concept_id(bundle, concept_id),
                "title": frontmatter["title"],
                "text": sec.text or "",
                "frontmatter": frontmatter,
            }
        )

    # Phase 2: derive sibling links, then write.
    links_by_index = _see_also_links(records, doc_name)
    created: list[str] = []
    for idx, record in enumerate(records):
        body = _render_body(record, links_by_index[idx])
        concept = bundle.write_concept(record["concept_id"], record["frontmatter"], body)
        created.append(concept.id)
        log.info("draft concept created: %s", _safe_log_text(concept.id))

    if created:
        indexlog.append_log(
            bundle,
            kind="Creation",
            message=f"ingested {safe_source} (--no-llm): {len(created)} draft concept(s)",
        )
    return created


__all__ = ["ingest_no_llm", "GENERATED_BY", "DESCRIPTION", "BODY_MAX_CHARS"]
