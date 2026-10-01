# okfsmith documentation

**okfsmith** is a Python CLI that converts messy documents (PDFs, markdown,
wiki dumps, Notion exports) into [OKF v0.2](https://github.com/GoogleCloudPlatform/open-knowledge-format)
knowledge bundles: markdown files with YAML frontmatter, plus reserved
`index.md` / `log.md` files — validated, visualized, and servable over MCP.

## Guides

- [Install](install.html) — requirements, extras, shell completion
- [Quickstart](quickstart.html) — your first bundle in five minutes
- [Commands](cli.html) — full CLI reference with examples
- [Ingesting & parsing](ingesting.html) — what `ingest` does stage by stage: PDF / Office / Notion inputs and parser tiers
- [LLM providers](providers.html) — Ollama, API keys, model configuration
- [Validation & error codes](validation.html) — conformance rules, exit codes
- [MCP server](mcp.html) — serve a bundle to agents (Claude, Cursor, Copilot, Gemini)
- [Skill pack](skill.html) — the `okfsmith-build` agent skill
- [Troubleshooting](troubleshooting.html) — common failures and fixes
- [FAQ](faq.html) — short answers
- [Architecture overview](https://github.com/Bilal-Junaid-Jiwani/okfsmith/blob/master/docs/OVERVIEW.md) — the eight-stage pipeline map

## Facts that matter

- **Spec**: OKF v0.2 (`GoogleCloudPlatform/open-knowledge-format`), §11 conformance rules enforced by `validate`.
- **License**: Apache-2.0.
- **Python**: 3.10+.
- **Offline-first**: parsing, sectioning, validation, and the graph viewer work with no network. Only LLM extraction needs a model endpoint.
- **No lock-in**: a bundle is plain markdown + YAML. Any tool that reads markdown can read it.

## For agents (llms.txt)

A compact machine-readable map of these docs: [`llms.txt`](llms.txt).
