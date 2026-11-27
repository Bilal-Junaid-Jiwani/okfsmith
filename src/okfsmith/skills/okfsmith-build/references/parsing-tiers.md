# Parsing Tiers — which parser for which input

`okfsmith ingest` turns raw documents into clean, ordered text before sectioning
and extraction. Parsing is tiered: Tier 1 is local and free; harder inputs
escalate only when needed.

## Tier 1 — local, free, keyless

| Input | Parser | Notes |
|---|---|---|
| PDFs (born-digital) | **LiteParse** | Reading-order recovery on text PDFs; always installed |
| `.md` / `.txt` | **stdlib text reader** | Read as UTF-8; markdown pipe tables extracted; always installed |
| `.docx` / `.pptx` / `.xlsx` / `.html` / `.csv` | **MarkItDown** | Requires the `office` extra: `pip install "okfsmith[office]"` |

Tier 1 never leaves the machine and needs no API keys or credentials. Office
formats without the extra are skipped with a clear error naming the extra.

## Tier 2 — Docling sidecar (optional)

For PDFs where Tier 1 produces garbled output: broken reading order,
complex multi-column layouts, heavy tables. Image-only pages are flagged
(`needs_ocr`) and reported as OCR escalation candidates instead of emitting
textless stubs — v1 performs no paid/cloud OCR. The `ocr` extra
(`pip install "okfsmith[ocr]"`, Docling) is available for heavier local
processing. Still local — just heavier.

## Tier 3 — OCR/vision tier (classification only in v1)

Scanned-image PDFs and standalone image files (no extractable text layer)
are classified `TIER3_OCR`: their pages are flagged `needs_ocr` and
reported, not silently stubbed. v1 ships no cloud OCR provider and sends
nothing off-machine — there is no API key to configure and no opt-in flag.
Treat `needs_ocr` pages as "needs a vision/OCR pass outside okfsmith" and
re-ingest the OCR'd text.

## Scan escalation policy

1. Try Tier 1 (LiteParse).
2. If the extracted text is sparse or garbage → try Tier 2 (Docling).
3. Pages with no text layer are classified Tier 3 (`needs_ocr`) and reported;
   run them through an external OCR/vision pass and re-ingest the text —
   v1 never sends page images anywhere itself.
4. Never OCR born-digital documents — a text layer that exists
   should be read, not OCR'd.

## Notion exports

Notion exports arrive as **zip files**. `okfsmith ingest` unzips them first,
then treats the contents as a multi-document input:

- Each exported page's `.md` file becomes a separate sectioning unit.
- Database views export as CSV and go through the MarkItDown path.
- Embedded files (PDFs, images) under the zip are parsed with the same
  tier policy above; images without a text layer are flagged `needs_ocr`,
  not silently stubbed.
- Notion's internal page-ID suffixes on filenames are stripped when forming
  concept IDs.

## Deliberate exclusions

- **PyMuPDF is excluded** from the stack (AGPL licensing).
- OCR is never applied silently: any page sent to Tier 3 is logged so the
  bundle's `log.md` can record it.
