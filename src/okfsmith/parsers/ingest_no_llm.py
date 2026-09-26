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

GENERATED_BY = "okfsmith/0.1.0"
DESCRIPTION = "Draft concept extracted without LLM; needs review"
BODY_MAX_CHARS = 8000


def _truncate(text: str, limit: int = BODY_MAX_CHARS) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit("\n", 1)[0] or text[:limit]
    return cut.rstrip() + "\n\n[... truncated: section body exceeds no-LLM limit ...]"


def ingest_no_llm(bundle: "Bundle", parsed: "ParsedDocument", source_id: str) -> list[str]:
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

    if (parsed.meta or {}).get("error"):
        log.warning("not ingesting %s: %s", source_id, parsed.meta["error"])
        return []

    sectioned = sectioning.section(parsed)
    if sectioned.too_small:
        log.info(
            "deferring entity creation for %s: source under %d chars "
            "(stub prevention)",
            source_id,
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
    used_slugs: set[str] = set()

    for i, sec in enumerate(sectioned.sections, start=1):
        span_pages = set(range(sec.page_span[0], sec.page_span[1] + 1))
        if span_pages and span_pages <= ocr_pages:
            # Entire section sits on OCR-flagged pages: report, don't stub.
            log.warning(
                "skipping section %r from %s: pages %s need OCR tier",
                sec.title,
                source_id,
                sorted(span_pages),
            )
            continue
        if not (sec.text or "").strip() and not sec.tables:
            continue  # empty section: nothing to draft

        base = slugify(sec.title) if sec.title else ""
        slug = base or f"section-{i}"
        n = 2
        while slug in used_slugs:
            slug = f"{base or f'section-{i}'}-{n}"
            n += 1
        used_slugs.add(slug)

        concept_id = f"{stem}/{slug}"
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
        log.info("draft concept created: %s", concept.id)

    if created:
        indexlog.append_log(
            bundle,
            kind="Creation",
            message=f"ingested {source_id} (--no-llm): {len(created)} draft concept(s)",
        )
    return created


__all__ = ["ingest_no_llm", "GENERATED_BY", "DESCRIPTION", "BODY_MAX_CHARS"]
