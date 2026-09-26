# Changelog

All notable changes to okfsmith. Format follows Keep a Changelog; versions
follow SemVer.

## [Unreleased]

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

## [0.1.0] — 2026-09-26

Initial public release: init/ingest/validate/list/graph CLI, OKF §11
validator, offline HTML graph viewer, MCP server, `okfsmith-build` skill pack.
