# okfsmith documentation

**okfsmith** is a Python CLI that converts messy documents (PDFs, markdown,
wiki dumps, Notion exports) into [OKF v0.2](https://github.com/GoogleCloudPlatform/open-knowledge-format)
knowledge bundles: markdown files with YAML frontmatter, plus reserved
`index.md` / `log.md` files — validated, visualized, and servable over MCP.

## Guides

- [Install](install.md) — requirements, extras, shell completion
- [Quickstart](quickstart.md) — your first bundle in five minutes
- [Commands](commands.md) — full CLI reference with examples
- [Pipeline](pipeline.md) — what `ingest` actually does, stage by stage
- [Parsing](parsing.md) — PDF / Office / Notion / zip inputs and parser tiers
- [LLM & no-LLM modes](llm.md) — Ollama, API keys, `--no-llm`, trust tiers
- [Validation & error codes](validation.md) — conformance rules, exit codes
- [MCP server](mcp.md) — serve a bundle to agents (Claude, Cursor, Copilot, Gemini)
- [Skill pack](skill.md) — the `okfsmith-build` agent skill
- [Troubleshooting](troubleshooting.md) — common failures and fixes
- [FAQ](faq.md) — short answers
- [Architecture overview](OVERVIEW.md) — the eight-stage pipeline map

## Facts that matter

- **Spec**: OKF v0.2 (`GoogleCloudPlatform/open-knowledge-format`), §11 conformance rules enforced by `validate`.
- **License**: Apache-2.0.
- **Python**: 3.10+.
- **Offline-first**: parsing, sectioning, validation, and the graph viewer work with no network. Only LLM extraction needs a model endpoint.
- **No lock-in**: a bundle is plain markdown + YAML. Any tool that reads markdown can read it.

## For agents (llms.txt)

A compact machine-readable map of these docs: [`llms.txt`](../llms.txt).
