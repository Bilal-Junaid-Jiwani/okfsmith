# Changelog

All notable changes to okfsmith. Format follows Keep a Changelog; versions
follow SemVer.

## [Unreleased]

### Added
- `okfsmith search BUNDLE QUERY`: BM25 full-text search over a bundle,
  stdlib-only (no new dependencies). Query syntax: bare terms, quoted
  phrases (`"knowledge graph"`), exclusions (`-deprecated`); an
  unbalanced quote is treated as a phrase, never an error. Tokenizer
  lowercases, splits on non-alphanumeric runs, drops ~40 English
  stopwords, and applies a small deterministic suffix stemmer
  (`sses→ss`, `ies→i`, `ing`/`ed`/`s` with length guards), so `running`
  matches `run`. Field weights: concept id/title ×3, description/tags
  ×2, body ×1; BM25 with k1=1.2, b=0.75; scores sort descending, ties
  broken by concept id for deterministic ordering. Flags: `--limit`/`-n`
  (default 10, must be ≥1), `--format text|json`, `--tier`, `--type`
  (same semantics as `list`). Text output is a rich table
  `Score | ID | Type | Title | Tier` (IDs never truncated) plus an
  `N result(s)` line; zero results exits 0 with `0 result(s)` and a
  stderr hint. JSON shape: `{"query", "results":
  [{"id","type","title","tier","score"}], "count"}`. Empty query is a
  usage error (exit 2); all failures print `error [CODE]:` + hint, never
  a traceback. The MCP server's `search` tool and the chat REPL's
  `/search` use the same engine, so CLI/MCP/chat results rank
  identically; `rank_concepts` is kept as a deprecated thin shim.
  No persistent on-disk index in v1 (built in memory per invocation;
  once at MCP startup). Guide: `docs/searching.md`.
- Docs: new `docs/searching.md` user guide (query syntax, tokenization,
  field weights, JSON shape, CLI/MCP/chat parity); README CLI table now
  lists `search`, documents `list --type`, and shows the correct
  `okfsmith chat v0.3.0` banner.

### Fixed
Fixed in this cycle from the pre-release QA audit (full details in the
QA bug report); criticals and highs listed, mediums/lows summarized.
- **Critical (10):** symlink escapes confined to the bundle root in
  `ensure_index`/`append_log` (C1); concept ids `index`/`log` no longer
  overwrite the reserved files (C2); same-stem files in different
  directories no longer silently overwrite each other on ingest (C3);
  non-mapping/invalid-YAML frontmatter is preserved, not silently
  discarded on load+resave (C4); UTF-16 sources no longer ingest as
  NUL-garbage concepts (C5); validator no longer follows symlinked
  `.md` files or blesses escaping links (C6); slug collisions no longer
  silently overwrite concepts (C7); non-UTF-8 `.md` now yields
  `error [unreadable-file]` naming the file instead of a
  `UnicodeDecodeError` traceback in `read`/`validate`/`list`/`graph`/
  `chat` (C8); impossible YAML dates report E001 instead of crashing
  with `ValueError` (C9); scalar `verified`/`tags` frontmatter
  (e.g. `verified: yes`) no longer crash MCP tools and CLI trust paths
  with `TypeError` (C10).
- **High (17):** unreadable directory-discovered files report a per-file
  "failed" row instead of aborting the batch with `PermissionError`
  (H1); concurrent ingests no longer lose index entries (H2);
  quadratic link regexes hardened against crafted-input DoS (H3); deep
  YAML nesting is caught instead of crashing with `RecursionError`
  (H4); text-only Notion exports (no `_files/` dir) are recognized
  (H5); nested ZIPs are parsed to documented depth 1 instead of being
  silently skipped (H6); `graph --output` no longer silently overwrites
  existing files (H7) and handles directory/missing-parent targets
  cleanly across formats (H8); `ingest` with a file path as the bundle
  emits `error [not-a-directory]` (H9); FIFO/non-file ingest sources
  get a clean error instead of `NotADirectoryError` (H10); `init` I/O
  failures surface `error [io-error]` (H11); directories named `*.md`
  no longer crash `list`/`read`/`validate` (H12); `read --format json`
  handles non-JSON-native frontmatter values (H13); null bytes in link
  targets no longer crash `graph` (H14); over-long titles are truncated
  to filesystem-safe lengths (H15); LLM transport failures retry instead
  of aborting the whole extraction run (H16); `Bundle.load` no longer
  hangs on a FIFO named `*.md` (H17).
- **Medium/low (30 + 25):** summary of the remaining audit fixes —
  BOM handling in titles/frontmatter (M9), latin-1 mojibake flagged not
  silently corrupted (M10), binary-file detection on ingest (M11), ghost
  concepts pruned on re-ingest (M1), `--dry-run` dedup-manifest parity
  (M18), parse errors reported accurately instead of the stub-prevention
  message (M2), phantom `'---'` concepts from frontmatter'd sources
  (M3), non-UTF-8 filename log encoding (M8), `validate --strict` output
  matches its exit code (M7), titled-link W001/W002 false positives
  (M12), code-block/graph-vs-validator link disagreements (M13, L3),
  mermaid node-ID collisions (M15), `check()` no longer creates missing
  dirs (M16), chat `/model` typo no longer kills the REPL session
  (M25), `graph --format text` inflection and other low-severity
  polish (L1–L25); stale `--bundle` flag usage removed from the MCP
  README (M26).

## [0.3.0] — 2026-09-26

### Added
- "Any model, any API key": `--provider` presets for 15 OpenAI-compatible
  endpoints (`openrouter`, `groq`, `mistral`, `deepseek`, `together`,
  `fireworks`, `deepinfra`, `anyscale`, `perplexity`, `xai`, `gemini`,
  `openai`, `agentrouter`, `lmstudio`, `ollama`) on `okfsmith ingest` and
  `okfsmith chat`, plus `--api-base` for literally anything else (Azure
  OpenAI, self-hosted vLLM / llama.cpp, any compat proxy). Keys via
  `OKFSMITH_API_KEY` (env, preferred), `--api-key` (with a one-time
  shell-history warning), `AGENTROUTER_API_KEY` (honored when the provider
  is `agentrouter`), or legacy `OPENAI_API_KEY`; models via `--model` /
  `OKFSMITH_MODEL`. OpenRouter is the flagship — one key routes to hundreds
  of models via `vendor/model`-style IDs. `okfsmith doctor` now reports the resolved
  provider, base URL, model, and key status (`set (hidden)` / `not set`) —
  keys are never displayed, logged, or persisted. Unknown `--provider`
  names fail loudly with the valid list. Anthropic's native API is not
  OpenAI-compatible: it needs a compat proxy via `--api-base` (or the
  `openrouter` preset).
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

### Changed
- `okfsmith chat` startup UI redesigned in the Qwen Code / Claude Code /
  Antigravity CLI aesthetic: giant gradient (yellow→orange→magenta) ASCII
  `OKFSMITH` logo, dimmed `okfsmith chat vX.Y.Z` line, Antigravity-style
  `Bundle: <name> (<N> concepts) · <provider> · <model>` info line,
  Qwen-style "Tips for getting started:" list, colored bundle-aware prompt
  (`kb ›`), and a subtle `✦` marker before answers. Piped / `NO_COLOR`
  output stays plain ASCII with zero escape codes. The banner no longer
  shows LLM key status (still in `/model` and `doctor`, masked).
- Documentation website: new static docs site in `docs/` (13 pages +
  `index.html`), styled after the Claude Code docs — warm dark theme, sticky
  topbar with search (Ctrl/Cmd+K), six-tab section bar, grouped sidebar nav,
  sticky "On this page" TOC, per-code-block and per-page copy buttons.
  Built by `python3 docs/build.py` (no npm, no build step); deploys as-is
  from GitHub Pages with `/docs` as the source folder. Includes
  `sitemap.xml`, `robots.txt`, `llms.txt`, JSON-LD metadata, `404.html`,
  and client-side search over a generated index.

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
