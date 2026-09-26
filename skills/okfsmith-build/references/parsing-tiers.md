# Parsing Tiers — which parser for which input

`okfsmith ingest` turns raw documents into clean, ordered text before sectioning
and extraction. Parsing is tiered: Tier 1 is local and free; harder inputs
escalate only when needed.

## Tier 1 — local, free, keyless (default for everything)

| Input | Parser | Notes |
|---|---|---|
| PDFs (born-digital) | **LiteParse** | Reading-order recovery on text PDFs |
| Everything else (markdown, HTML, docx, xlsx, pptx, csv, …) | **MarkItDown** | Microsoft's document-to-markdown converter |
| Plain `.md` / `.txt` | passthrough | Already structured; no parsing needed |

Tier 1 never leaves the machine and needs no API keys or credentials.

## Tier 2 — Docling sidecar (optional)

For PDFs where Tier 1 produces garbled output: broken reading order,
complex multi-column layouts, heavy tables. Enable with the sidecar flag on
`okfsmith ingest` (see `okfsmith ingest --help`). Still local — just heavier.

## Tier 3 — cloud OCR (opt-in, scans only)

Scanned-image PDFs (no extractable text layer) are the *only* input that may
use Tier 3. It is off by default and must be explicitly enabled; it sends
page images to a hosted OCR provider, so it requires a configured API key
and a decision that the content may leave the machine.

## Scan escalation policy

1. Try Tier 1 (LiteParse).
2. If the extracted text is sparse or garbage → try Tier 2 (Docling).
3. Escalate to Tier 3 **only** when the document is genuinely scanned
   (no text layer) **and** the user has opted in.
4. Never use Tier 3 for born-digital documents — a text layer that exists
   should be read, not OCR'd.

## Notion exports

Notion exports arrive as **zip files**. `okfsmith ingest` unzips them first,
then treats the contents as a multi-document input:

- Each exported page's `.md` file becomes a separate sectioning unit.
- Database views export as CSV and go through the MarkItDown path.
- Embedded files (PDFs, images) under the zip are parsed with the same
  tier policy above; unscanned images are skipped with a note, not OCR'd
  without opt-in.
- Notion's internal page-ID suffixes on filenames are stripped when forming
  concept IDs.

## Deliberate exclusions

- **PyMuPDF is excluded** from the stack (AGPL licensing).
- OCR is never applied silently: any page sent to Tier 3 is logged so the
  bundle's `log.md` can record it.
