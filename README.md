# okfsmith

[![PyPI](https://img.shields.io/pypi/v/okfsmith.svg)](https://pypi.org/project/okfsmith/)
[![Python](https://img.shields.io/pypi/pyversions/okfsmith.svg)](https://pypi.org/project/okfsmith/)
[![License](https://img.shields.io/github/license/Bilal-Junaid-Jiwani/okfsmith.svg)](https://github.com/Bilal-Junaid-Jiwani/okfsmith/blob/main/LICENSE)

**Forge messy documents into Google's Open Knowledge Format (OKF) v0.2 knowledge bundles.**

okfsmith is a Python CLI that ingests messy sources — PDFs, markdown, wiki dumps, Notion exports — and emits spec-conformant OKF v0.2 bundles: markdown files with YAML frontmatter, an `index.md`, and a `log.md`. Every concept carries provenance (`sources[]`), a trust tier, and lifecycle metadata, and every bundle is checked by a built-in §11 validator. Serve it to your agents with one MCP command.

## 60-second quickstart

```bash
# install via pip, or run straight from uvx
pip install okfsmith

# start a bundle
okfsmith init ./kb

# ingest a messy PDF — local, free parsing; no API keys needed
okfsmith ingest ./kb docs/quarterly-report.pdf

# validate against OKF §11
okfsmith validate ./kb
# 42 concepts · 0 errors · 3 warnings

# serve it to your agent over MCP (stdio)
uvx okfsmith mcp --bundle ./kb
```

Point any MCP-capable agent at the stdio server — tools are `search`, `get`, `list`, `neighbors`, `index` — and every answer traces back to `sources[]` in the bundle.

## Why okfsmith

OKF is a clean, LLM-readable knowledge standard. But the tooling around it all starts from clean inputs:

| Starting point | What exists | The gap |
|---|---|---|
| Clean markdown | `okf-cli` (markdown → bundle) | — |
| Code repositories | code-graph tools | — |
| **Messy PDFs, wikis, Notion exports** | **nothing** | **← okfsmith** |

Real-world knowledge lives in 200-page PDFs with broken reading order, sprawling Notion exports, and wiki dumps. okfsmith is the ingestion-first CLI that forges those into first-class OKF bundles:

**parse → section → extract → link → emit → validate → serve**

## Features

- **Tiered parsing, free first.** Tier 1 is local and keyless: LiteParse for PDFs, MarkItDown for everything else — born-digital documents never leave your machine. Optional Tier 2 (Docling sidecar) and Tier 3 (cloud OCR, opt-in) cover scanned or pathological pages.
- **2-pass LLM extraction.** A cheap model drafts concept JSON with a contextual situating prefix (doc title + section path + doc summary) stamped into each concept; a critic pass verifies contradictions, claim fidelity, and stubs. Claims become `[^source-id]` footnotes feeding `sources[]` — provenance is structural, not decorative. Local Ollama by default; hosted models only via env vars.
- **OKF v0.2 native.** Only `type` is required in frontmatter. okfsmith also emits `sources[]`/provenance, `generated`/`verified` trust metadata, and `status`/`stale_after` lifecycle fields.
- **§11 validator.** Implements the spec's three hard conformance rules, plus advisory lints (orphans, dead links, stubs, missing recommended fields, legacy v0.1 fields). Broken links are warnings, never errors (spec §6).
- **One-command MCP server.** `uvx okfsmith mcp --bundle ./kb` — FastMCP over stdio.
- **SKILL.md pack.** Ship agent instructions alongside your bundle so assistants know how to read it.
- **Graph visualization.** `okfsmith graph` renders `viz.html` to browse the concept graph in a browser.

## CLI reference

| Command | What it does |
|---|---|
| `okfsmith init ./kb` | Scaffold a new OKF v0.2 bundle |
| `okfsmith ingest ./kb <source>…` | Parse sources → extract concepts → link → emit |
| `okfsmith validate ./kb` | Check OKF §11 conformance (hard rules + advisory lints) |
| `okfsmith list ./kb` | List concepts in the bundle |
| `okfsmith read ./kb <concept>` | Print a concept with its frontmatter |
| `okfsmith graph ./kb` | Render `viz.html` for the concept graph |
| `okfsmith mcp --bundle ./kb` | Serve the bundle over MCP (stdio) |

`okfsmith <command> --help` shows full options. See [docs/OVERVIEW.md](docs/OVERVIEW.md) for the pipeline each command drives.

## How it compares

| | **okfsmith** | okf-cli | Go / Rust OKF tools | Graphify-style tools |
|---|---|---|---|---|
| Language | Python | Python | Go / Rust | varies |
| Starts from | messy PDFs, wikis, Notion exports | clean markdown | existing bundles | code repos |
| Primary job | **ingestion → OKF** | markdown → bundle | validation / conversion | code graphs |
| Trust tiers + provenance | yes, v0.2 native | — | varies | n/a |
| MCP server | yes, one command | — | varies | — |

Honest framing: clean markdown in → `okf-cli` is fine. Validating or converting existing bundles → the Go/Rust tools do that well. okfsmith is Python-first and ingestion-first — it exists for the messy documents nobody else handles.

## Trust tiers

Every concept carries a trust tier, derived from the pipeline — no manual bookkeeping:

| Tier | Meaning | Set when |
|---|---|---|
| `unverified` | Extracted, not yet confirmed | after ingest (default) |
| `machine-confirmed` | Passed the critic verification pass | after Pass 2 of extraction |
| `human-reviewed` | A person signed off | `verified:` stamped on review |

Extraction stamps `generated: {by: <tool>/<model>, at: <timestamp>}`; `verified:` is only set after review. Together with `status` and `stale_after`, every concept answers four questions: what it is, where it came from, how much to trust it, and when to re-check it.

## Configuration

Zero config to start — Tier 1 parsing is local and free. LLM features default to a local Ollama model; set these only if you want hosted models:

| Variable | Purpose | Default |
|---|---|---|
| `OKFSMITH_MODEL` | Model for 2-pass extraction | local Ollama model |
| `ANTHROPIC_API_KEY` | Optional: use Anthropic models | unset (local only) |
| `OPENAI_API_KEY` | Optional: use OpenAI models | unset (local only) |

Keys are read from the environment only — never from files, flags, or the repo.

## Development

```bash
git clone https://github.com/Bilal-Junaid-Jiwani/okfsmith
cd okfsmith
pip install -e .
pytest
```

`src/` layout: `core/` holds the business logic (parsing, extraction, linking, validation, bundle I/O); `cli/` is the thin Typer layer. Optional extras: `.[mcp]`, `.[ocr]`. Every slice ships with tests; nothing merges without review.

## Roadmap

On the way to 1.0: first PyPI release, wider Tier 2/3 coverage for hard scans, incremental re-ingest with LLM-adjudicated dedup, richer advisory lints.

What v1 will **not** do — by design:

- **No vector database.** Search stays lexical + graph-based. Your bundle is plain files: grep it, diff it, version-control it.
- **No attestation runtime.** okfsmith records provenance; it does not execute attestations.

## Contributing

Issues and PRs are welcome at [github.com/Bilal-Junaid-Jiwani/okfsmith](https://github.com/Bilal-Junaid-Jiwani/okfsmith). Conventional commits, tests with every change, no secrets in the repo.

## License

Apache-2.0 — see [LICENSE](https://github.com/Bilal-Junaid-Jiwani/okfsmith/blob/main/LICENSE).

## Acknowledgments

- Google's [Open Knowledge Format](https://github.com/GoogleCloudPlatform/open-knowledge-format) spec (v0.2) — the standard okfsmith implements.
- LiteParse (Apache-2.0) and MarkItDown (MIT) — the free, local parsing backbone.
- FastMCP, Typer, and Ollama — the serving, CLI, and local-model layers.
