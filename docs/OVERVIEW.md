# okfsmith — Architecture Overview

The okfsmith pipeline turns raw, messy documents into validated OKF v0.2 bundles and serves them to agents. Eight stages, strictly ordered — each stage's output is the next stage's input.

```
raw documents (PDFs, markdown, wiki dumps, Notion exports)
                        │
                        ▼
┌──────────────────────────────────────────────┐
│ 1. INGEST                                    │
│ collect sources · SHA-256 dedup              │
│ capture provenance in log.md                 │
└──────────────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────┐
│ 2. PARSE                                     │
│ Tier 1: LiteParse (PDFs) + MarkItDown        │
│ local & free · Tier 2: Docling sidecar       │
│ Tier 3: cloud OCR (scans only, opt-in)       │
└──────────────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────┐
│ 3. SECTION                                   │
│ chunk by headings / pages                    │
│ keep title + section path + summary          │
└──────────────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────┐
│ 4. EXTRACT                                   │
│ 2-pass LLM: cheap draft + critic             │
│ claims -> [^source-id] -> sources[]          │
└──────────────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────┐
│ 5. LINK                                      │
│ dedup & merge (LLM-adjudicated)              │
│ build the relation graph                     │
└──────────────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────┐
│ 6. EMIT                                      │
│ write OKF v0.2: md + YAML frontmatter        │
│ index.md + log.md                            │
└──────────────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────┐
│ 7. VALIDATE                                  │
│ OKF §11: 3 hard rules = errors               │
│ + advisory lints = warnings                  │
└──────────────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────┐
│ 8. SERVE                                     │
│ FastMCP stdio: search / get / list /         │
│ neighbors / index  ·  viz.html               │
└──────────────────────────────────────────────┘
```

## Stage details

**1. Ingest.** The entry point for raw sources. `okfsmith ingest` copies each source into the bundle's source store, hashes it with SHA-256 to dedup identical files, and records provenance (origin path, capture time) in the bundle log. Nothing is parsed here — this stage exists to establish an immutable record of exactly what went in, so every concept can later trace back to a byte-identical source.

**2. Parse.** Raw documents become clean, ordered text. Tier 1 is free, local, and keyless: LiteParse handles PDFs, MarkItDown handles everything else, and born-digital documents never leave the machine. Tier 2 (an optional Docling sidecar) and Tier 3 (cloud OCR — opt-in, for scanned pages only) cover the hard cases. PyMuPDF is deliberately excluded from the stack (AGPL).

**3. Section.** Parsed text is split into coherent sections along the document's own structure (headings, pages), and each chunk keeps its lineage: document title, section path, and a short document summary. That lineage is what the extraction stage stamps into every concept as its contextual situating prefix — the reason each concept knows precisely which part of which document it came from.

**4. Extract.** Two LLM passes turn sections into OKF concepts. Pass 1 uses a cheap model to draft concept JSON with the contextual situating prefix embedded per concept. Pass 2 is a critic that rejects contradictions, claim infidelity, and stubs. Individual claims are anchored as `[^source-id]` footnotes that become `sources[]` frontmatter entries, and `generated: {by: <tool>/<model>, at: <timestamp>}` is stamped on every concept. Local Ollama is the default; hosted models are used only when API keys are provided via environment variables.

**5. Link.** Duplicates are resolved and relationships are built. SHA-256 source dedup, normalized-title/resource matching, and embedding similarity propose merges; the LLM adjudicates ambiguous cases. Surviving concepts are wired into a relation graph (reflected in `index.md`), which powers `neighbors` queries and the `viz.html` visualization. Per spec §6, broken links surface as warnings, never errors.

**6. Emit.** The bundle is written to disk as OKF v0.2: one markdown file per concept with YAML frontmatter (only `type` is required; `sources[]`/provenance, `generated`/`verified`, and `status`/`stale_after` are emitted when available), a generated `index.md`, and an append-only `log.md`. Everything is plain files, so bundles diff cleanly in version control.

**7. Validate.** OKF §11 is implemented natively: the spec's three hard conformance rules are errors, and everything else is advisory lints — orphans, dead links, stubs, missing recommended fields, legacy v0.1 fields. Validation is the gate before a bundle ships or is served: zero errors required, warnings reported for the author to triage.

**8. Serve.** The bundle is exposed read-only, never mutated. `uvx okfsmith mcp --bundle ./kb` starts a FastMCP server over stdio with `search`, `get`, `list`, `neighbors`, and `index` tools, so agents read concepts — with their provenance — directly. For humans, `okfsmith graph` renders `viz.html` to browse the concept graph in a browser.

## Cross-cutting constraints

- **No vector database.** Search is lexical plus graph traversal; the bundle stays plain files.
- **No secrets in the repo.** API keys come from the environment only, never from files or flags.
- **Thin CLI, fat core.** The Typer CLI layer drives `core/` business logic; `mcp` and `ocr` are optional install extras.
