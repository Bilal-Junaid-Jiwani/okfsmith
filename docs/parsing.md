# Parsing

`okfsmith ingest` parses each source file into a structured document (pages,
text, tables, metadata) before sectioning and extraction. Parsers are chosen
by file type, in tiers.

## Parser tiers

| Tier | What | When |
|------|------|------|
| 1 — local, always available | **LiteParse** for PDFs (text-based; constructed with `ocr_enabled=False`, never calls paid OCR APIs); stdlib markdown/text | default for `.pdf`, `.md`, `.txt` |
| 1 — local, optional extra | **MarkItDown** for Office files (`okfsmith[office]`): `.docx`, `.pptx`, `.xlsx` | Office formats |
| 2 — sidecar | **Docling** (`okfsmith[ocr]`) for scanned/image PDFs | `--ocr` escalation path |
| 3 — opt-in | cloud OCR | scans only, explicit opt-in |

PyMuPDF is deliberately **not** used (AGPL license).

## Notion exports

Notion HTML/CSV exports are parsed directly: pages become sections, databases
become per-row concepts where the export structure allows it. Zip archives
(`.zip`) are unpacked with guards: max 100,000 members, max 512 MiB total
uncompressed, and every member path is contained inside the destination
(ZipSlip-safe).

## Markdown and text

`.md` / `.txt` files are parsed with the stdlib: headings become section
boundaries, existing YAML frontmatter is preserved and merged (never
silently dropped).

## Failure behavior

- A source that cannot be parsed is reported per file in the ingest summary
  table (`failed: <reason>`); other sources still ingest.
- Exception text from parsers is treated as untrusted and escaped before it
  reaches terminal output (no markup injection).
- `--dry-run` runs parsing + sectioning and reports what *would* be created,
  writing nothing.
