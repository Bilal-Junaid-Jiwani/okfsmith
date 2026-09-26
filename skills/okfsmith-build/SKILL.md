---
name: okfsmith-build
description: >-
  Builds OKF v0.2 knowledge bundles from messy documents with okfsmith, the
  open-source Python CLI that converts PDFs, markdown, wiki dumps, and Notion
  exports into spec-conformant knowledge bundles with provenance, trust tiers,
  and lifecycle metadata. Use when an agent needs to convert docs to OKF:
  scaffold a bundle (init), ingest sources (ingest), check OKF v0.2
  conformance (validate), or serve a bundle to agents over MCP. Trigger
  keywords: okf, knowledge bundle, convert docs to OKF, ingest PDF to
  knowledge base, bundle validator, open knowledge format. Do NOT use for
  code-graph extraction from repositories (use Graphify-style tools), for
  executing attested computations (okfsmith packages the computation
  interface; running it is the consumer's job), for already-clean
  markdown-only pipelines where okf-cli is simpler, or as a general-purpose
  document search engine.
---

# okfsmith-build

Forge messy documents into Google's Open Knowledge Format (OKF) v0.2 bundles
with **okfsmith**, a Python-first, ingestion-first CLI: PDFs, wiki dumps, and
Notion exports in; spec-conformant markdown bundles with provenance
(`sources[]`), trust tiers (`generated`/`verified`), and lifecycle metadata
out.

## When to use

- Converting PDFs, markdown collections, wiki dumps, or Notion exports into
  an OKF v0.2 knowledge bundle.
- Validating an existing bundle against the OKF §11 conformance rules.
- Serving a finished bundle to agents (Claude Code, Cursor, Copilot,
  Gemini CLI) over MCP.
- Auditing or enriching a bundle's provenance and trust metadata.

## When NOT to use

- **Code-graph extraction** from source repositories — that is what
  Graphify-style tools are for; okfsmith ingests *documents*, not code.
- **Executing attested computations** — OKF fixes the computation's
  interface (`runtime`, `parameters`, `executor`, `attester`), not its
  packaging or execution. okfsmith emits the concept; running it is the
  consumer's job.
- **Already-clean markdown pipelines** — if the input is tidy markdown with
  no parsing or extraction needed, `okf-cli` may be simpler.
- As a general document search engine — okfsmith builds bundles; search
  happens over the finished bundle via the MCP `search` tool.

## Quickstart

```bash
# 1. init — scaffold a new OKF v0.2 bundle
okfsmith init ./kb

# 2. ingest — parse sources → extract concepts → link → emit
#    Tier 1 parsing is local and free; no API keys needed.
okfsmith ingest ./kb docs/quarterly-report.pdf
okfsmith ingest ./kb ~/exports/notion-export.zip wiki-dump/

# 3. validate — check OKF §11 conformance (hard rules + advisory lints)
okfsmith validate ./kb
# or with the bundled stdlib-only script (works without okfsmith installed):
python3 scripts/validate.py ./kb   # exit 0 conformant, 1 errors, 2 usage error

# 4. mcp — serve the bundle to your agent over stdio
okfsmith mcp ./kb
# tools exposed: search, get, list, neighbors, index
```

Newly ingested concepts land as `unverified`; Pass 2 of extraction promotes
them to `machine-confirmed`; a human stamping `verified:` promotes them to
`human-reviewed` (see the cheatsheet).

## Decision table

| Situation | Action |
|---|---|
| Messy docs (PDFs, wiki dumps, Notion exports) → new bundle | `okfsmith init` + `okfsmith ingest` |
| Clean markdown only, no extraction needed | consider `okf-cli` instead (simpler) |
| Existing bundle, check conformance | `okfsmith validate` or `scripts/validate.py` |
| Existing bundle, serve to agents | `okfsmith mcp ./kb` (see `references/mcp-recipes.md`) |
| Scanned-image PDFs | escalate parsing per `references/parsing-tiers.md` (Tier 3 is opt-in) |
| Repo of source code → knowledge graph | not okfsmith — use a code-graph tool |

## Gotchas

- **Only `type` is required.** A concept carrying just `type` is fully
  conformant. Never invent required fields, and never reject a bundle for
  missing optional frontmatter, unknown types, or unknown extra keys (§11).
- **Broken links are warnings, not errors.** A link target missing from the
  bundle may be not-yet-written knowledge; consumers must tolerate it (§6.1).
  The fallback validator (`scripts/validate.py`) emits errors only.
- **The `human:` prefix drives trust tiers.** `verified` by `human:alice`
  ⇒ `human-reviewed`; by `process:` or `<agent>/<model>` only ⇒
  `machine-confirmed`; no `verified` ⇒ `unverified`. Normalize a bare-mapping
  `verified:` to a one-element list *before* deriving the tier (§5.2, §11).
- **Root `index.md` alone may carry `okf_version`.** No other frontmatter in
  any `index.md`; none at all in `log.md`. Reserved names are case-sensitive:
  `Index.md` is a concept, not an index.
- **Concept ID = path minus `.md`.** `finance/revenue.md` is concept
  `finance/revenue`. Non-`.md` files (`.py`, `.sql`) are not concepts.
- **`log.md` date headings must be valid ISO `YYYY-MM-DD` calendar dates**
  (`## 2026-05-22`), newest first. The leading bold word (`**Update**`) is a
  convention, not a requirement.
- **`sources[].resource` is required *within* a sources entry**, but
  path-valued fields are never link-checked (they may be scope descriptors
  or point at not-yet-created files).
- **Attested Computation**: `runtime` is required for the type; the agent
  supplies *values* for declared `parameters` and must never author or edit
  the computation. Receipts are runtime artifacts, never bundle content.
- **Attribution is keyed, not positional.** Footnote labels (`[^ga4-schema]`)
  join to `sources[].id`; never cite by list position.
- **No network, no secrets.** Tier 1 parsing is local. Tier 3 cloud OCR is
  opt-in and scans-only. LLM extraction defaults to a local Ollama model;
  hosted models need explicit API keys via environment variables.

## References (one level deep)

- `references/okf-v02-cheatsheet.md` — condensed v0.2 frontmatter, index,
  log, linking, and conformance reference.
- `references/parsing-tiers.md` — which parser for which input (LiteParse
  for PDFs, MarkItDown for everything else, scan escalation, Notion zips).
- `references/mcp-recipes.md` — client configs (Claude Code, Cursor,
  Copilot, Gemini CLI) to attach `okfsmith mcp`.

## Scripts

- `scripts/validate.py` — stdlib-only OKF §11 validator. Uses
  `okfsmith.validate.check` when the package is installed; otherwise falls
  back to a minimal 4-error-rule (E001–E004) check. Emits machine-readable
  JSON: `{bundle, engine, conformant, errors[], warnings[]}`; exit 0 =
  conformant, 1 = errors found, 2 = usage/IO failure.
