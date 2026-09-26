---
title: Ingesting documents
eyebrow: User guide
description: How okfsmith ingest turns PDFs, Markdown, Office files and more into draft concepts — the free --no-llm path first, then LLM extraction when you need it.
---

## Ingest your first document

The `--no-llm` path is free, deterministic, and needs no API key — it's the recommended first step:

```bash
okfsmith init ./kb
okfsmith ingest ./kb guide.md --no-llm
```

(`guide.md` is the sample document from the [Quickstart](quickstart.html) — or point it at any of your own Markdown files.)

Real output (verified run — your SHA and concept count will differ per file):

```
    Ingest summary — sectioning (no LLM)
┏━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━┓
┃ File     ┃ SHA-256      ┃ Concepts ┃ Status ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━┩
│ guide.md │ 00902a6ea326 │        5 │ ok     │
└──────────┴──────────────┴──────────┴────────┘
ingested 5 concept(s) from 1 file(s) into kb
```

## Supported formats

The parser is tiered and free-first — it routes each file by type:

| Input | Parser | Cost / setup |
|---|---|---|
| `.md`, `.txt` | LiteParse-free text parser (stdlib only) | Free, built in |
| `.pdf` | LiteParse | Free, built in, fully offline |
| Notion export (zip) | Notion parser | Free, built in |
| `.docx`, `.pptx`, `.xlsx`, `.html`, `.csv`, `.zip`, images | MarkItDown | Needs `pip install "okfsmith[office]"` |
| Scanned/image-only PDFs | OCR sidecar | Needs `pip install "okfsmith[ocr]"` |

```bash
# a directory of files at once (add --recursive for subdirectories)
okfsmith ingest ./kb docs/ --recursive --no-llm
```

> [!TIP]
> Not sure which extras you have? Run `okfsmith doctor` — it shows each extra as `OK` or `MISSING` with the install command. Office support is the `markitdown` extra.

## The `--no-llm` free-first flow

With `--no-llm`, okfsmith uses **deterministic sectioning** instead of a language model:

1. You pass one or more files (or directories).
2. Each file is parsed to text.
3. The text is split into sections by headings.
4. Each section becomes one **draft concept** with a generated id like `big/installation` (file slug / heading slug).
5. Concept files are written into the bundle.

Because it's deterministic, running it twice on the same file gives the same result — and per-file **SHA-256 dedup** means re-ingesting the same file changes nothing (the bundle manifest tracks digests).

## What happens under the hood

Every source runs through the same ordered stages — each stage's output is the
next stage's input:

```
source file
  │ 1. COLLECT — gather files (recursive if asked), skip already-ingested
  │              via SHA-256 fingerprints
  ▼
  │ 2. PARSE — bytes → structured document (pages, text, tables, metadata)
  ▼
  │ 3. SECTION — split into titled sections (headings / page spans)
  ▼
  │ 4. EXTRACT — sections → concept drafts
  │              • --no-llm: one draft concept per section (offline, fast)
  │              • LLM: two-pass draft + critic; claims cite [^source-id]
  ▼
  │ 5. WRITE — concepts land as <bundle>/<source-slug>/<slug>.md with
  │            YAML frontmatter: `type: Draft`, `title`, `description`,
  │            `resource` (source file), `generated` (by/at), `status: draft`,
  │            tags `draft` / `no-llm` (the LLM path also records `sources[]`)
  ▼
  │ 6. INDEX/LOG — index.md refreshed, log.md appended (provenance)
```

Concept ids follow `file-slug/heading-slug`, e.g. `big/first-bundle`.

> [!NOTE]
> Without `--no-llm`, ingest uses the **LLM extraction path** by default (model, provider, and API-key flags apply). If no LLM is reachable in that mode, ingest **errors** — it never silently falls back to `--no-llm`.

## Parser tiers

Parsers are chosen by file type, in tiers:

| Tier | What | When |
|------|------|------|
| 1 — local, always available | **LiteParse** for PDFs (text-based; constructed with `ocr_enabled=False`, never calls paid OCR APIs); **stdlib reader** for `.md` / `.txt` | default for `.pdf`, `.md`, `.txt` |
| 1 — local, optional extra | **MarkItDown** for Office files (`okfsmith[office]`): `.docx`, `.pptx`, `.xlsx`, plus `.html`, `.csv`, images | Office formats |
| 2 — sidecar | **Docling** (`okfsmith[ocr]`) for scanned/image PDFs | image-only pages are flagged (`needs_ocr`) and reported as OCR escalation candidates |
| 3 — classification only | **OCR/vision tier** (no provider in v1) | scans/images flagged `needs_ocr` and reported; nothing leaves the machine |

PyMuPDF is deliberately **not** used (AGPL license).

## Notion exports, zip files, and plain text

- **Notion exports** — Notion HTML/CSV exports are parsed directly: each page (and each per-database CSV file) becomes one parsed document, and sections within it become draft concepts through the normal pipeline — not one concept per CSV row.
- **Zip archives** (`.zip`) are unpacked with guards: max 100,000 members, max 512 MiB total uncompressed, and every member path is contained inside the destination (ZipSlip-safe).
- **`.md` / `.txt`** files are parsed with the stdlib: headings become section boundaries, existing YAML frontmatter is preserved and merged (never silently dropped).
- A source that cannot be parsed is reported per file in the ingest summary table (`failed: <reason>`); other sources still ingest.

## The 1000-char skip rule (stub prevention)

In `--no-llm` mode, files with **under ~1000 characters** are skipped:

```
Status: skipped (below 1000-char minimum; stub prevention)
```

This is deliberate: tiny files would become "stub" concepts too thin to be useful. If a file is legitimately short, merge it into a larger document before ingesting.

## Duplicate headings get `-2`, `-3` suffixes

Heading slugs must be unique within a file. If a document repeats a heading, later concepts get numeric suffixes:

```
concept one        →  doc/concept-one
concept one (2nd)  →  doc/concept-one-2
concept one (3rd)  →  doc/concept-one-3
```

The same applies to heading-less sections, which fall back to `section-<n>`.

## `--dry-run`: parse and plan only

Preview what ingest *would* do without writing anything to the bundle:

```bash
okfsmith ingest ./kb report.pdf --dry-run
```

The summary table still prints — concept counts per file, skip reasons — but the bundle is untouched. Use it before a big batch ingest.

<details>
<summary>Advanced</summary>

- `--recursive` — recurse into subdirectories when a source is a directory.
- `--quiet` / `-q` — only warnings, errors, and the final summary line.
- `--provider <str>` / `--model <str>` / `--api-base <url>` / `--api-key <key>` — LLM extraction path settings (the env-var equivalents `OKFSMITH_PROVIDER`, `OKFSMITH_MODEL`, `OKFSMITH_API_BASE`, `OKFSMITH_API_KEY` are preferred — `--api-key` lands in shell history). See [Providers](providers.html).
- Corrupt or unreadable files never crash a run — they're logged as warnings and skipped with `meta["error"]` set.

</details>

---

**Next: [Providers & API keys →](providers.html)** — ready for richer extraction? Wire up an LLM provider.
