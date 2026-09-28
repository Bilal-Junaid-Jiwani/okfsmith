---
title: Changelog
eyebrow: Troubleshooting
description: Release history for okfsmith — what changed in each version, what's coming next, and upgrade notes. Follows Keep a Changelog and Semantic Versioning.
---

## [0.4.0] — 2026-09-28 {#v0-4-0}

### Added {#unreleased-added}

- **`okfsmith sync`** — incremental sync of a bundle with its sources:
  SHA-256 change detection, `added` / `updated` / `renamed` / `removed`
  handling (renames detected by content hash, updates replace under the
  same ids — never `name-2` duplicates), atomic resumable state,
  `--watch` polling, `--dry-run`, `--format json`. See
  [Syncing sources](syncing.html).
- **Temporal knowledge model** — concepts carry `valid_from` /
  `valid_until` validity windows, `supersedes` replacement chains, and
  `last_verified` freshness; retrieval ranks by currency, and
  `--as-of <date>` on `search` / `eval` replays any instant. Superseded
  concepts are hidden by default, never deleted. See
  [Temporal model](temporality.html).
- **MCP expansion** — four new read tools: `traverse` (BFS link-graph
  expansion, depth ≤ 3, cycle-safe), `provenance` (concept → sources →
  ingest manifest), `diff` (bundle vs bundle or vs sync snapshot), plus
  evidence budgets on every tool (`max_chunks`, `max_tokens`,
  `continuation_token`) for bounded agent context. See
  [MCP server](mcp.html).
- **`okfsmith eval`** — golden Q&A eval harness: scores golden sets on the
  RAG Triad (context relevancy / faithfulness / answer relevancy),
  diagnoses failures as retrieval vs generation, runs heuristic (keyless)
  or LLM-judge, and gates CI with `--fail-under`. See
  [Evaluating bundles](eval.html).
- **Governed MCP write-back** — four new tools (`preview_write_concept`,
  `write_concept`, `update_concept`, `audit_log`) let agents contribute
  under code-enforced governance: writes always land at the `unverified`
  trust tier, human-reviewed concepts need explicit `downgrade_trust`,
  validator-gated, atomic, append-only audited. See
  [MCP server](mcp.html).

## [0.3.0] — 2026-09-26 {#v0-3-0}

### Added {#v030-added}

- **Interactive chat REPL** (`okfsmith chat`) — ask questions over your
  bundle in natural language, Claude-Code style: citations, slash
  commands (`/search`, `/read`, `/validate`, `/graph`, `/doctor`, …),
  extractive fallback when no LLM is reachable, and generative answers
  via Ollama or any OpenAI-compatible provider. See
  [Interactive chat](chat.html).
- **Any-model provider system** — 15 `--provider` presets
  (`ollama`, `lmstudio`, `openai`, `groq`, `mistral`, `deepseek`,
  `openrouter`, `together`, `fireworks`, `deepinfra`, `anyscale`,
  `perplexity`, `xai`, `gemini`, `agentrouter`), plus `--api-base` /
  `OKFSMITH_API_BASE` for any other OpenAI-compatible endpoint. Keys are
  never displayed, logged, or saved to disk. See
  [Providers & API keys](providers.html).
- **Chat startup UI** — Qwen/Claude/Antigravity-style makeover: gradient
  ASCII `OKFSMITH` banner, bundle-aware `kb ›` prompt, and `✦` answer
  markers. Piped and `NO_COLOR` output stays plain.
- **This documentation website** — the Claude-Code-style docs you are
  reading, now live at
  [bilal-junaid-jiwani.github.io/okfsmith](https://bilal-junaid-jiwani.github.io/okfsmith/)
  via GitHub Pages.

## [0.2.0] — 2026-09-26 {#v0-2-0}

### Added {#v020-added}

- `okfsmith doctor` — environment check covering dependencies, optional
  extras, Ollama reachability, and API-key status (keys are always
  reported as `set (hidden)`, never echoed).
- `--format json` output for `list`, `read`, `validate`, and `graph`
  for scripting and CI.
- `--dry-run` for `ingest` — parse and plan without writing anything.
- Shell completion via `okfsmith --install-completion` /
  `--show-completion`, plus a man page.
- Progress bars for long ingests.

### Fixed

- Graph viewer (`viz.html`) pointer-event bug — click and drag now work
  in the interactive visualization.
- README/CLI help-text mismatches — documented commands and flags now
  match the real CLI exactly.

### Security

- Link containment in ingested content.
- Zip-bomb guards on archive inputs.
- Symlink skipping during directory ingestion.
- Fixed a HIGH-severity CVE in the MarkItDown dependency.

### Upgrade notes

Upgrade with `pip install --upgrade okfsmith`. No bundle migration is
needed — bundles created by earlier versions validate unchanged.
`okfsmith search`, `okfsmith get`, and `okfsmith completions` were never
CLI commands (search/get are MCP tools and chat slash commands;
completion uses `--install-completion`).

## Links {#links}

- Full release history with downloadable artifacts:
  [github.com/Bilal-Junaid-Jiwani/okfsmith/releases](https://github.com/Bilal-Junaid-Jiwani/okfsmith/releases)
- Source repository:
  [github.com/Bilal-Junaid-Jiwani/okfsmith](https://github.com/Bilal-Junaid-Jiwani/okfsmith)
