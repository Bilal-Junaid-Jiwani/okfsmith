# okfsmith

[![PyPI](https://img.shields.io/pypi/v/okfsmith.svg)](https://pypi.org/project/okfsmith/)
[![Python](https://img.shields.io/pypi/pyversions/okfsmith.svg)](https://pypi.org/project/okfsmith/)
[![License](https://img.shields.io/github/license/Bilal-Junaid-Jiwani/okfsmith.svg)](https://github.com/Bilal-Junaid-Jiwani/okfsmith/blob/main/LICENSE)

**Forge messy documents into [OKF v0.2](https://github.com/GoogleCloudPlatform/open-knowledge-format) knowledge bundles.**

okfsmith is a Python CLI that ingests PDFs, markdown, wiki dumps, and Notion
exports and emits spec-conformant OKF v0.2 bundles: markdown files with YAML
frontmatter, plus reserved `index.md` and `log.md`. Every concept carries
provenance (`sources[]`), a trust tier, and lifecycle metadata, and every
bundle is checked by a built-in §11 validator. Serve it to your agents with
one MCP command.

## 60-second quickstart

```bash
pip install okfsmith

okfsmith init ./kb
okfsmith ingest ./kb notes/ report.pdf --no-llm   # offline first pass
okfsmith validate ./kb
okfsmith graph ./kb --format html   # writes ./kb/viz.html — open in a browser
```

Point any MCP-capable agent at the bundle:

```bash
pip install "okfsmith[mcp]"
okfsmith mcp ./kb
```

Tools exposed: `index`, `list`, `search`, `get`, `neighbors` — every answer
traces back to `sources[]` in the bundle.

## Why okfsmith

Clean markdown already has good OKF tooling. The messy middle — 200-page PDFs
with broken reading order, sprawling Notion exports, wiki dumps — is where
knowledge usually lives, and that's what okfsmith ingests first:

**parse → section → extract → link → emit → validate → serve**

- **Tiered parsing, free first.** Tier 1 is local and keyless: LiteParse for
  PDFs, stdlib parsing for markdown/text. Office formats (`.docx`, `.pptx`,
  `.xlsx`) via the optional `okfsmith[office]` extra; Docling OCR sidecar via
  `okfsmith[ocr]` for scanned pages. PyMuPDF is deliberately avoided (AGPL).
- **Two extraction modes.** `--no-llm` writes one draft concept per section —
  fast, offline, deterministic. With an LLM (Ollama by default, or an
  OpenAI-compatible API via env vars), a draft + critic flow extracts claims
  with `[^source-id]` citations feeding `sources[]`.
- **OKF v0.2 native.** Only `type` is required in frontmatter. okfsmith also
  emits `sources[]`/provenance, `generated`/`verified` trust metadata, and
  lifecycle fields.
- **§11 validator.** The spec's hard conformance rules (E001–E003) plus
  advisory lints (dead links, orphans, stubs, legacy v0.1 fields). Broken
  links are warnings, never errors (spec §6).
- **Graph visualization.** `okfsmith graph --format html` renders a
  self-contained `viz.html` (works offline): nodes colored by type with a
  colorblind-safe palette, shaped by trust tier, with backlinks, search, and
  keyboard access.
- **One-command MCP server.** `okfsmith mcp ./kb` over stdio, SSE, or
  streamable HTTP.
- **Skill pack.** `skills/okfsmith-build/SKILL.md` teaches agents the
  init → ingest → validate → serve loop.

## CLI reference

| Command | What it does |
|---|---|
| `okfsmith init BUNDLE` | scaffold `index.md` + `log.md` |
| `okfsmith ingest BUNDLE SOURCE...` | parse, section, extract → draft concepts |
| `okfsmith validate BUNDLE` | check OKF §11 conformance (exit 0 = conformant) |
| `okfsmith list BUNDLE` | list concepts (filter by `--tier`) |
| `okfsmith read BUNDLE ID` | print one concept |
| `okfsmith graph BUNDLE` | links: text / json / mermaid / html |
| `okfsmith mcp BUNDLE` | serve over MCP |
| `okfsmith doctor` | check dependencies, extras, Ollama |

The bundle is always the first positional argument. Expected failures print
`error [CODE]:` with a hint and never a traceback; usage errors exit 2.

Full reference with examples: [docs/commands.md](docs/commands.md).

## Install options

```bash
pip install "okfsmith[office]"   # DOCX / PPTX / XLSX
pip install "okfsmith[mcp]"      # MCP server
pip install "okfsmith[ocr]"      # Docling OCR sidecar
pipx install "okfsmith[office,mcp]"
```

`okfsmith doctor` verifies your setup.

## Docs

[Documentation index](docs/index.md) · [Quickstart](docs/quickstart.md) ·
[Pipeline](docs/pipeline.md) · [Validation](docs/validation.md) ·
[MCP](docs/mcp.md) · [Troubleshooting](docs/troubleshooting.md) ·
[FAQ](docs/faq.md)

## License

Apache-2.0. See [LICENSE](LICENSE).
