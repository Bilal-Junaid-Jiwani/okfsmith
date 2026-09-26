"""Plain-text parsing with the stdlib only (no optional extras needed).

Covers ``.md`` / ``.markdown`` / ``.txt``. The file's raw bytes go through
a small detection pipeline -- never ``errors="replace"``, so undecodable
input either decodes properly or is rejected outright:

1. **Binary check** -- NUL bytes that are not part of UTF-16, or a high
   control-character ratio after decoding, raise
   :class:`BinaryContentError`. ``parse_file()`` catches it and maps it to
   a warn-and-skip empty document, so a binary blob never becomes a
   garbage concept (M11).
2. **Encoding detection** -- UTF-16 is detected via BOM or a NUL-byte
   heuristic and decoded properly (C5); a UTF-8 BOM is stripped via
   ``utf-8-sig`` (M9); then strict UTF-8 is tried, with a windows-1252
   fallback that emits a ``logging`` warning (M10) -- never silent
   U+FFFD replacement characters.
3. **Frontmatter strip** -- a leading YAML frontmatter block is removed
   from markdown sources so it cannot become a body section (M3).
4. **Sectioning** happens downstream in
   :mod:`okfsmith.parsers.sectioning` on the cleaned text.

Markdown pipe tables are extracted into ``Page.tables`` via
:func:`okfsmith.parsers.office.markdown_tables`, which is a pure function
and does not require MarkItDown.

This keeps the base install (no ``office`` extra) able to ingest the most
common knowledge sources: markdown notes and plain text.
"""

from __future__ import annotations

import logging
import unicodedata
from pathlib import Path

import yaml

from . import Page, ParsedDocument
from .office import markdown_tables

log = logging.getLogger(__name__)

_UTF8_BOM = b"\xef\xbb\xbf"
_UTF16_LE_BOM = b"\xff\xfe"
_UTF16_BE_BOM = b"\xfe\xff"

_MARKDOWN_SUFFIXES = frozenset({".md", ".markdown"})

# How much of the file head is sampled for the encoding/binary heuristics.
_SAMPLE_SIZE = 8192
# NUL bytes in >= this fraction of sampled positions, concentrated on one
# byte parity, means UTF-16 without a BOM (C5).
_UTF16_NUL_FRACTION = 0.30
# Decoded text is treated as binary when more than this fraction of the
# sampled characters are control characters (M11).
_CONTROL_CHAR_FRACTION = 0.05


class BinaryContentError(ValueError):
    """A ``.md``/``.txt`` source looks like binary data, not text.

    Raised by :func:`parse_text_file` instead of emitting a garbage
    concept. :func:`okfsmith.parsers.parse_file` catches it and maps it
    to a warn-and-skip empty document (``meta["error"]`` is set) -- the
    same clean path used for every other unparseable file.
    """


def _utf16_no_bom(raw: bytes) -> str | None:
    """Detect UTF-16 without a BOM via the NUL-byte pattern (C5).

    UTF-16-encoded Latin text stores NULs in almost every other byte
    (odd positions for little-endian, even positions for big-endian).
    Returns the codec name, or None when the pattern is absent.
    """
    if b"\x00" not in raw:
        return None
    sample = raw[:_SAMPLE_SIZE]
    half = max(1, len(sample) // 2)
    odd_nuls = sum(1 for b in sample[1::2] if b == 0)
    even_nuls = sum(1 for b in sample[0::2] if b == 0)
    if odd_nuls / half >= _UTF16_NUL_FRACTION and odd_nuls > 3 * even_nuls:
        return "utf-16-le"
    if even_nuls / half >= _UTF16_NUL_FRACTION and even_nuls > 3 * odd_nuls:
        return "utf-16-be"
    return None


def _looks_binary(text: str) -> bool:
    """True when control characters dominate the sampled text (M11).

    Tab, LF, and CR are legitimate prose whitespace and are excluded;
    everything else in Unicode category Cc (NUL, ESC, BEL, ...) is a
    strong binary signal.
    """
    sample = text[:_SAMPLE_SIZE]
    if not sample:
        return False
    n_control = sum(
        1 for ch in sample if ch not in "\t\n\r" and unicodedata.category(ch) == "Cc"
    )
    return n_control / len(sample) > _CONTROL_CHAR_FRACTION


def _decode(raw: bytes, path: Path) -> str:
    """Binary check + encoding detection -> str (C5, M9, M10, M11).

    Raises :class:`BinaryContentError` for binary-looking input.
    """
    # BOMs are checked before the NUL-byte binary check: a BOM'd UTF-16
    # file of non-Latin text may contain no NUL bytes at all.
    if raw.startswith(_UTF8_BOM):
        text = raw.decode("utf-8-sig")  # M9: the BOM is stripped
    elif raw.startswith((_UTF16_LE_BOM, _UTF16_BE_BOM)):
        try:
            text = raw.decode("utf-16")  # C5: BOM consumed by the codec
        except (UnicodeDecodeError, ValueError) as exc:
            raise BinaryContentError(
                f"{path.name}: undecodable as UTF-16 ({exc}); not ingested"
            ) from exc
    elif b"\x00" in raw:
        # NUL bytes: either UTF-16 without a BOM, or binary (M11).
        codec = _utf16_no_bom(raw)
        if codec is None:
            raise BinaryContentError(
                f"{path.name}: looks like binary data (NUL bytes); not ingested"
            )
        try:
            text = raw.decode(codec)
        except (UnicodeDecodeError, ValueError) as exc:
            raise BinaryContentError(
                f"{path.name}: undecodable as {codec} ({exc}); not ingested"
            ) from exc
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            # M10: latin-1-ish input decodes losslessly under windows-1252;
            # warn via logging so the fallback is never silent, and never
            # emit U+FFFD replacement characters.
            log.warning("%s: not valid UTF-8; decoding as windows-1252", path.name)
            text = raw.decode("windows-1252")

    if _looks_binary(text):
        raise BinaryContentError(
            f"{path.name}: looks like binary data "
            "(high control-character ratio); not ingested"
        )
    return text


def _strip_frontmatter(text: str, suffix: str) -> str:
    """Strip a leading YAML frontmatter block from markdown sources (M3).

    The block is removed only when it parses as a YAML mapping, so a
    document that merely opens with a horizontal rule keeps its content.
    """
    if suffix not in _MARKDOWN_SUFFIXES:
        return text
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            block = "".join(lines[1:i])
            try:
                data = yaml.safe_load(block) if block.strip() else None
            except yaml.YAMLError:
                return text
            if isinstance(data, dict):
                return "".join(lines[i + 1 :]).lstrip("\n")
            return text
    return text


def parse_text_file(path: str | Path) -> ParsedDocument:
    """Read a markdown / plain-text file into a single-page ParsedDocument.

    Runs the reader pipeline -- binary check, BOM/encoding detection,
    YAML frontmatter strip -- before returning the page; downstream
    sectioning (:mod:`okfsmith.parsers.sectioning`) then sees clean text.

    Raises :class:`BinaryContentError` for binary-looking input so a
    garbage concept is never emitted; :func:`okfsmith.parsers.parse_file`
    maps it to a warn-and-skip empty document. Unreadable paths still
    return an empty document with ``meta["error"]`` set.
    """
    from . import _empty  # local import: avoid a cycle at module load

    p = Path(path)
    try:
        raw = p.read_bytes()
    except OSError as exc:
        return _empty(f"{type(exc).__name__}: {exc}", p)
    text = _decode(raw, p)  # binary check + encoding detection (may raise)
    text = _strip_frontmatter(text, p.suffix.lower())
    page = Page(number=1, text=text, tables=markdown_tables(text))
    return ParsedDocument(
        pages=[page],
        meta={"source": str(p), "tier": "TIER1_LOCAL", "parser": "text"},
    )
