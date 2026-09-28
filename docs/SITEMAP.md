# okfsmith docs site — Sitemap & Information Architecture

Target layout mirrors <https://code.claude.com/docs/en/setup>:
dark theme · top nav · tab bar · left sidebar · main content · right "On this page" TOC.
The site is served from the `/docs` subpath on GitHub Pages, so **every URL is
relative** — no leading `/` anywhere (links like `install.html`, never
`/docs/install.html`).

---

## 1. Page list

Every page: slug (URL filename), title, one-line description.

| # | Slug | Title | Description |
|---|------|-------|-------------|
| 1 | `install.html` | Installation | Install okfsmith from PyPI, add optional extras (office/mcp/ocr), set up shell completion, verify with `okfsmith doctor`. |
| 2 | `quickstart.html` | Quickstart | Five minutes from zero to a validated, visualized knowledge bundle: `init` → `ingest --no-llm` → `validate` → `graph`. |
| 3 | `dashboard.html` | Web dashboard | The local web UI: launch, ingest documents, explore the knowledge graph, chat with citations — all ten product areas, with screenshots. |
| 4 | `chat.html` | Interactive chat | Ask questions over your bundle in the Claude-Code-style REPL: citations, slash commands, extractive fallback, Ollama/OpenAI-compatible answers. |
| 5 | `ingesting.html` | Ingesting documents | What `ingest` does: parser tiers (LiteParse, MarkItDown, Docling sidecar), PDF/Office/Notion/zip inputs, sectioning, SHA-256 dedup, `--no-llm` vs LLM extraction, trust tiers. |
| 6 | `providers.html` | Providers & API keys | The 15 OpenAI-compatible `--provider` presets, API keys via `OKFSMITH_API_KEY` / `--api-key`, `--api-base` for anything else, model resolution order, how `doctor` reports key status without ever showing keys. |
| 7 | `syncing.html` | Syncing sources | What `sync` does: SHA-256 change detection, add/update/rename/remove handling, atomic resumable state, `--watch` polling, `--dry-run`, `--format json`. |
| 17 | `eval.html` | Evaluating bundles | Score golden Q&A sets on the RAG Triad: context relevancy / faithfulness / answer relevancy, per-question reporting, retrieval-vs-generation diagnosis, CI gating. |
| 8 | `validation.html` | Validation & error codes | OKF v0.2 §11 conformance: errors E001–E004, warnings W001–W006, `--strict`, `--format json`, stable CLI error codes and exit codes. |
| 9 | `graph.html` | Visualizing the knowledge graph | `graph` output formats (text/json/mermaid/html), the offline interactive `viz.html` viewer: colorblind-safe palette, trust-by-shape legend, backlinks, search, keyboard access. |
| 10 | `skill.html` | Agent skill pack | The `okfsmith-build` skill: what it teaches agents (init → ingest → validate → serve), where it lives, trigger phrases, scope limits. |
| 11 | `faq.html` | FAQ | Short answers: what OKF is, no-LLM option, data privacy, Python versions, PyMuPDF/AGPL, Anthropic's non-compatible API. |
| 12 | `cli.html` | CLI reference | One page, one section per command with flags and examples: `init`, `ingest`, `sync`, `list`, `read`, `validate`, `graph`, `doctor`, `chat`, `mcp`, `completions`; plus `search` and `get` (MCP tools and chat slash commands — they are not CLI commands, see notes). |
| 13 | `mcp.html` | MCP server | Serve a bundle to agents over MCP: stdio/SSE/streamable-HTTP transports, the `index`/`list`/`search`/`get`/`neighbors` tools, client config for Claude Code/Desktop, Cursor, Copilot, Gemini. |
| 14 | `troubleshooting.html` | Troubleshooting | Every common failure: `slice-not-installed`, `llm-unavailable`, `not-a-bundle`, zero-concept ingests, stub prevention, empty graph, with fixes and the "run `doctor` and file an issue" fallback. |
| 15 | `changelog.html` | Changelog | Release history (Keep a Changelog / SemVer): what changed per version, `Unreleased` section, upgrade notes. |
| 16 | `temporality.html` | Temporal model | Time-aware knowledge: validity windows, supersession chains, as-of queries, and how freshness interacts with trust tiers. |

Notes on the required CLI command list (from the coordinator brief):
- `get` and `search` are **not** CLI commands in okfsmith — they are MCP server
  tools (`mcp_server/server.py`), and equivalents exist as the chat slash
  commands `/read` and `/search`. The CLI reference covers them in dedicated
  `cli.html#search-and-get` sections so users find them where they expect, and
  points at `mcp.html` for tool semantics. The CLI analogues are `list` and
  `read`.
- `completions` is covered by Typer's built-in `completion` command plus the
  static scripts in `completions/` (bash/zsh) — documented in `cli.html`
  and linked from `install.html`.

## 2. Tab bar mapping

Each page belongs to exactly one tab.

| Tab | Pages (in order) | Default landing page |
|-----|------------------|----------------------|
| **Getting started** | `install.html` → `quickstart.html` → `dashboard.html` → `chat.html` | `install.html` |
| **User guide** | `ingesting.html` → `validation.html` → `syncing.html` → `eval.html` → `graph.html` → `skill.html` → `faq.html` | `ingesting.html` |
| **CLI reference** | `cli.html` | `cli.html` |
| **Providers** | `providers.html` | `providers.html` |
| **MCP** | `mcp.html` | `mcp.html` |
| **Troubleshooting** | `troubleshooting.html` → `changelog.html` | `troubleshooting.html` |

Rationale: the tab bar is the six tabs specified. `chat.html` sits in
*Getting started* because it is the payoff of the beginner flow
(install → quickstart → **ask your docs questions**). `providers.html` gets
its own tab because API-key/provider wiring is the #1 setup friction for LLM
mode — one click away from any tab. `ingesting.html` merges the existing
`pipeline.md` + `parsing.md` + no-LLM sections of `llm.md` into one guided
page rather than three parallel reads.

## 3. Left sidebar groups

Claude-docs style groups per tab, top to bottom, beginner-first.

**Getting started** tab:
- Group: **Start here**
  1. Installation *(tab landing)*
  2. Quickstart
  3. Interactive chat

**User guide** tab:
- Group: **Building bundles**
  1. Ingesting documents *(tab landing)*
  2. Validation & error codes
  3. Visualizing the knowledge graph
- Group: **More**
  4. Agent skill pack
  5. FAQ

**CLI reference** tab:
- Group: **Reference**
  1. CLI reference *(tab landing — single page, all commands with anchors:
     `#init`, `#ingest`, `#list`, `#read`, `#search-and-get`, `#validate`,
     `#graph`, `#doctor`, `#chat`, `#mcp`, `#completions`)*

**Providers** tab:
- Group: **Configuration**
  1. Providers & API keys *(tab landing)*

**MCP** tab:
- Group: **Serve**
  1. MCP server *(tab landing)*

**Troubleshooting** tab:
- Group: **Help**
  1. Troubleshooting *(tab landing)*
  2. Changelog

## 4. Homepage decision

**`index.html` renders the Installation page** (same content as `install.html`).

Why Installation over Quickstart:
1. It mirrors the reference interface exactly — Claude Code docs lands on
   `/docs/en/setup` (install/setup), not on a quickstart.
2. `pip install okfsmith` is a hard prerequisite; landing here eliminates the
   "command not found" dead end for true beginners.
3. The page ends with a prominent "Continue to Quickstart →" CTA, so the
   magic demo (`init` → `ingest` → `validate` → `graph`) is exactly one click
   away — the beginner flow is install → quickstart → chat regardless.

The top nav also links `install.html` directly, and `index.html` should carry
a `<link rel="canonical">` pointing at the install URL so search engines see
one page, not two.

## 5. Cross-links — "next page" flows

The sidebar order already implies the flows; in addition, each page ends with
an explicit **Next →** link so a beginner never has to guess.

**Core beginner flow (the happy path):**
1. `install.html` → **Next: Quickstart →**
2. `quickstart.html` → **Next: Web dashboard →**
3. `dashboard.html` → **Next: Interactive chat →**
4. `chat.html` → **Next: Ingesting documents →**

**Going deeper:**
4. `ingesting.html` → **Next: Providers & API keys →**
   (needed the moment you drop `--no-llm`)
5. `providers.html` → **Next: CLI reference →**
   (you now know all flags; the reference is your cheat sheet)
6. `cli.html` → **Next: MCP server →**
   (bundle built — serve it to agents)
7. `mcp.html` → **Next: Troubleshooting →**
   (when client config or transports misbehave)

**Contextual cross-links (not just linear):**
- `quickstart.html` step 3 → link `validation.html` ("what the §11 rules mean")
- `quickstart.html` step 4 → link `graph.html` ("all viewer features")
- `ingesting.html` no-LLM section → link `providers.html` ("ready for richer extraction?")
- `install.html` extras section → link `ingesting.html` parser tiers ("which extra do I need?")
- `troubleshooting.html` every error section → link the relevant page
  (`llm-unavailable` → `providers.html`, `slice-not-installed` → `install.html`,
  E001–E004/W001–W006 → `validation.html`)
- `troubleshooting.html` footer → link `changelog.html` ("fixed in a newer version?")
- `cli.html` header → link `quickstart.html` ("learn by doing first")
- `mcp.html` `search`/`get` tools → link `cli.html#search-and-get` (CLI analogues)

**Rules for all links:** relative paths only (`quickstart.html`,
`cli.html#ingest`), never leading `/`. No page links to a non-existent slug;
the 13 slugs in §1 are the complete link universe.
