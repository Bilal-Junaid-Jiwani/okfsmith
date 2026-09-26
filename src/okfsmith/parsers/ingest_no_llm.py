"""--no-llm ingest: ParsedDocument -> DRAFT concepts, no LLM involved.

Emits one DRAFT concept per section with structure-only frontmatter.
Sources that are too small, failed to parse, or whose sections come only
from OCR-flagged pages produce no concepts (stub prevention); what would
need OCR is reported, never stubbed.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from okfsmith.core.bundle import Bundle

    from . import ParsedDocument

log = logging.getLogger(__name__)

GENERATED_BY = "okfsmith/0.2.0"
DESCRIPTION = "Draft concept extracted without LLM; needs review"
BODY_MAX_CHARS = 8000


def _truncate(text: str, limit: int = BODY_MAX_CHARS) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit("\n", 1)[0] or text[:limit]
    return cut.rstrip() + "\n\n[... truncated: section body exceeds no-LLM limit ...]"


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


def _alloc_concept_id(bundle: Bundle, stem: str, slug: str, used: set[str]) -> str:
    """Allocate a concept id for ``stem/slug`` that collides with nothing.

    Mirrors the LLM path's ``_concept_id_for`` (C3): the bundle is consulted
    via ``bundle.get()`` — not just the per-file ``used`` set — so two
    same-stem files in different directories can never silently overwrite
    each other's concepts. Appends ``-2``, ``-3``, … on collision and records
    the allocated (stored-form) id in ``used``.
    """
    candidate = f"{stem}/{slug}"
    n = 2
    while True:
        stored = _stored_concept_id(bundle, candidate)
        if stored not in used and bundle.get(stored) is None:
            used.add(stored)
            return candidate
        candidate = f"{stem}/{slug}-{n}"
        n += 1


def ingest_no_llm(bundle: Bundle, parsed: ParsedDocument, source_id: str) -> list[str]:
    """Ingest a ParsedDocument into *bundle* as DRAFT concepts.

    Returns the list of created concept ids. Creates nothing (returns [])
    when the source failed to parse, is too small to be meaningful, or has
    no parseable sections left after OCR-flagged pages are excluded.
    """
    from okfsmith.core import indexlog
    from okfsmith.core.bundle import slugify
    from okfsmith.core.spec import utc_now_iso

    from . import sectioning
    from .router import ocr_escalations

    # M8: source_id may hold undecodable bytes (surrogate escapes); never let
    # the raw value reach a log message or append_log (UnicodeEncodeError).
    safe_source = _safe_log_text(source_id)

    if (parsed.meta or {}).get("error"):
        log.warning("not ingesting %s: %s", safe_source, parsed.meta["error"])
        return []

    sectioned = sectioning.section(parsed)
    if sectioned.too_small:
        log.info(
            "deferring entity creation for %s: source under %d chars "
            "(stub prevention)",
            safe_source,
            sectioning.TOO_SMALL_CHARS,
        )
        return []

    ocr_pages = {
        pg.number for pg in (parsed.pages or []) if pg.needs_ocr
    }
    if ocr_pages:
        for msg in ocr_escalations(parsed):
            log.warning("ingest: %s", msg)

    stem = Path(source_id).stem or "document"
    created: list[str] = []
    used_ids: set[str] = set()

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
        concept_id = _alloc_concept_id(bundle, stem, slug, used_ids)
        frontmatter = {
            "type": "Draft",
            "title": sec.title or f"Section {i} of {Path(source_id).name}",
            "description": DESCRIPTION,
            "resource": str(source_id),
            "generated": {"by": GENERATED_BY, "at": utc_now_iso()},
            "status": "draft",
            "tags": ["draft", "no-llm"],
        }
        body = _truncate(sec.text)
        concept = bundle.write_concept(concept_id, frontmatter, body)
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
