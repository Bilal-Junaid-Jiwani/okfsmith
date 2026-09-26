"""Tier routing: decide which parsing tier a source file needs.

Tiers:
    TIER1_LOCAL - born-digital documents parsed locally, fully offline
                  (PDF via liteparse, office formats via MarkItDown).
    TIER3_OCR   - scanned / image-only sources: no text layer exists.

v1 does NOT call paid OCR APIs (llamaparse / mistral / azure). Pages that
need OCR are reported via :func:`ocr_escalations` so the caller can record
them in its run report instead of emitting a textless stub — emitting a
textless stub is FORBIDDEN.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import ParsedDocument

import logging
from enum import Enum
from pathlib import Path

log = logging.getLogger(__name__)

OCR_MESSAGE = (
    "page {n} has no text layer — needs OCR tier "
    "(llamaparse/mistral/azure); skipping OCR in v1"
)


class Tier(str, Enum):
    TIER1_LOCAL = "TIER1_LOCAL"
    TIER3_OCR = "TIER3_OCR"


_IMAGE_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif", ".webp"}
)


def route(path: str | Path) -> Tier:
    """Route a source file to its parsing tier.

    Born-digital formats (default) -> TIER1_LOCAL. Standalone image files
    have no text layer by definition -> TIER3_OCR. Scanned PDFs are still
    routed TIER1_LOCAL for extraction; their image-only *pages* are flagged
    via Page.needs_ocr and reported by :func:`ocr_escalations`.
    """
    suffix = Path(path).suffix.lower()
    if suffix in _IMAGE_SUFFIXES:
        log.info("routing %s -> TIER3_OCR (image file, no text layer)", path)
        return Tier.TIER3_OCR
    return Tier.TIER1_LOCAL


def ocr_escalations(parsed: ParsedDocument) -> list[str]:
    """Messages for pages that would be escalated to the OCR tier in v1.

    v1 skips paid OCR entirely; callers should record these messages in the
    run report instead of emitting textless stubs for the pages.
    """
    source = (parsed.meta or {}).get("source", "?")
    messages: list[str] = []
    for page in parsed.pages or []:
        if page.needs_ocr:
            messages.append(f"{source}: " + OCR_MESSAGE.format(n=page.number))
    for m in messages:
        log.warning(m)
    return messages


__all__ = ["Tier", "route", "ocr_escalations", "OCR_MESSAGE"]
