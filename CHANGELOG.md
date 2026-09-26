# Changelog

All notable changes to okfsmith. Format follows Keep a Changelog; versions
follow SemVer.

## [Unreleased]

### Added
- `okfsmith chat BUNDLE`: interactive Claude Code / Gemini CLI style REPL over
  a bundle — natural-language questions answered with `[concept-id]` citations,
  multi-turn follow-ups resolved against recent context, slash commands
  (`/help`, `/ingest`, `/list`, `/read`, `/search`, `/validate`, `/graph`,
  `/doctor`, `/model`, `/clear`, `/exit`), persistent line history at
  `~/.okfsmith/history`. Generative answers via Ollama (default) or
  `OPENAI_API_KEY`; falls back to extractive mode when no LLM is reachable
  (`--no-llm` forces it). Hallucinated citations are stripped — every cited
  concept is a real bundle concept.
- `rank_concepts()` in `okfsmith.mcp_server.server`: shared retrieval ranking
  used by both the MCP `search` tool and the chat REPL.

## [0.2.0] — 2026-09-26

### Added
- Positional bundle argument across all commands (`okfsmith ingest BUNDLE SOURCE...`)
- `okfsmith doctor` environment check (dependencies, extras, Ollama, writability)
- JSON output modes for `list` and `read`; `validate --format json` now reports top-level `status`, `concepts`, `error_count`, `warning_count`
- `ingest` flags: multiple sources, `--recursive`, `--dry-run`, `--quiet`, TTY progress
- `init --force` confirmation (bypass with `--yes`)
- Constrained `--format` / `--tier` / `--transport` choices (exit 2 on misuse)
- Stable CLI error codes (`error [CODE]:` + hint, no tracebacks); JSON error objects for JSON commands
- Interactive graph viewer upgrades: `#empty[hidden]` fix, Okabe–Ito colorblind-safe palette, trust-by-shape legend, keyboard access, Esc handling, screen-reader concept list, backlinks in detail panel, minimal-markdown rendering, reset view, match count, neighborhood emphasis, loading/error states
- Rich-markup escaping for all dynamic CLI table content
- Security regression test suite (`tests/test_security.py`)
- Docs: install/quickstart/commands/pipeline/parsing/llm/validation/mcp/skill/troubleshooting/faq guides, `llms.txt`

### Changed
- MarkItDown moved to the optional `office` extra (leaner default install)
- Dependency bounds tightened (typer, pyyaml, rich, httpx, liteparse, fastmcp, docling, pytest)
- PyPI metadata: description, keywords, classifiers, project URLs

### Security
- markitdown floor `>=0.1.5` (CVE-2025-11849 mammoth arbitrary file read; CVE-2025-64512 pdfminer.six RCE)
- Link targets contained inside the bundle root (escaping links become dead links)
- ZipSlip-safe extraction with member-count and total-size caps
- `Bundle.load` skips symlinked concepts and reserved files
- Subdir traversal rejected in index/log helpers
- Human-review errors no longer disclose absolute bundle paths
- Viz `safeHref`: strip leading C0 controls before scheme check (blocks `\x01javascript:` bypass); behavioral node regression test
- Viz `md()`: `javascript:`/`data:`/`vbscript:`/protocol-relative URLs never become anchors

### Fixed
- Sub-1000-char ingest reports `skipped (below 1000-char minimum; stub prevention)` instead of hollow `ok`; digest not recorded; `--dry-run` parity
- `okfsmith mcp` without the `mcp` extra emits `error [missing-extra]` + hint (no traceback)
- `init` on a file path emits `error [not-a-directory]` (no traceback)
- `graph --output` works for json/mermaid/text (was silently ignored); graph JSON includes `dead_links`
- `list` IDs never truncate (copy-paste safe); empty `list` shows next-step hint
- `ruff check src/ tests/` fully clean; CI workflow fixed (master trigger, cross-platform smoke, honest PyMuPDF check)
- Docs: trust derived from `verified` (not a literal `trust:` field); embedding similarity labeled v1 TODO; Notion CSV = one document each; canonical spec URLs in examples

## [0.1.0] — 2026-09-26

Initial public release: init/ingest/validate/list/graph CLI, OKF §11
validator, offline HTML graph viewer, MCP server, `okfsmith-build` skill pack.
