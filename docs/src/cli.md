---
title: CLI reference
eyebrow: CLI reference
description: Every okfsmith command on one page — init, ingest, sync, list, read, validate, graph, doctor, chat, mcp — with real syntax, flags, and runnable examples.
---

## CLI reference

One page, every command. New here? Start with [the quickstart](quickstart.html) to learn by doing — this page is the cheat sheet you keep open afterwards.

> [!NOTE]
> **Looking for `get`?** It is not a CLI command — `get` exists as an **MCP server tool** (see [the MCP server page](mcp.html)) and as the `/read` chat slash command (inside [chat](chat.html)); the CLI analogue is [`read`](#okfsmith-read). Full-text search *is* a CLI command now: [`okfsmith search`](#okfsmith-search). Shell completion is not a command either — it's the global `--install-completion` flag (see [Global flags](#global-flags)).

All examples assume a bundle at `./kb` created with `init` (paths like `kb` and `big.md` come straight from verified runs — adapt them to your own files).

---

## Global flags

These work on every command, including with no subcommand:

| Flag | What it does |
|---|---|
| `--help` | Show help for the CLI or a specific command (`okfsmith ingest --help`). |
| `--version` | Print the version (e.g. `0.3.0`) and exit. |
| `--format json` | Where supported (`list`, `read`, `validate`, `graph`, `sync`): emit machine-readable JSON instead of rich text. |
| `--no-llm` | Where supported (`ingest`, `sync`, `chat`): run fully deterministic, no LLM involved. |
| `--install-completion` | Install shell completion for the current shell. |
| `--show-completion` | Print the completion script instead of installing it. |

> [!TIP]
> JSON output always has a stable top-level shape, e.g. `{"concepts": [{"id", "type", "title", "tier"}]}` for `list`. Pipe it to `jq` in scripts.

---

## okfsmith init

Create a new, empty OKF bundle in BUNDLE.

```bash
okfsmith init [OPTIONS] {bundle}
```

```bash
okfsmith init ./kb
```

Real output — `init` scaffolds exactly two files, `index.md` and `log.md`, nothing else:

```text
Initialized OKF bundle in kb
  index: /path/to/kb/index.md
  log:   /path/to/kb/log.md
Next: add sources with 'okfsmith ingest kb <file-or-dir> --no-llm'.
```

### Common options {#init-options}
| Flag | What it does |
|---|---|
| `--force` | Scaffold even if the bundle exists and is non-empty (asks for confirmation). |
| `--yes`, `-y` | Answer "yes" to the `--force` prompt — for non-interactive use. |

---

## okfsmith ingest

Ingest documents into BUNDLE as draft concepts.

```bash
okfsmith ingest [OPTIONS] {bundle} {sources}...
```

```bash
# Deterministic, no-LLM path — the recommended first run
okfsmith ingest ./kb big.md --no-llm

# Ingest a whole directory tree
okfsmith ingest ./kb ./docs --recursive --no-llm
```

Real output (the table and summary line are exactly what you see):

```text
    Ingest summary — sectioning (no LLM)
┏━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━┓
┃ File   ┃ SHA-256      ┃ Concepts ┃ Status ┃
┡━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━┩
│ big.md │ 34a0dca378f8 │       18 │ ok     │
└────────┴──────────────┴━━━━━━━━━━┴━━━━━━━━┘
ingested 18 concept(s) from 1 file(s) into kb
```

### Common options {#ingest-options}
| Flag | What it does |
|---|---|
| `--no-llm` | Deterministic sectioning, no LLM needed. Start here. |
| `--dry-run` | Parse and plan only — write nothing. |
| `--quiet`, `-q` | Only warnings, errors, and the final summary line. |
| `--recursive` | Recurse into subdirectories when a SOURCE is a directory. |
| `--provider`, `--model`, `--api-base`, `--api-key` | LLM extraction settings (default path when `--no-llm` is *not* passed). See [Providers & API keys](providers.html). |

<details>
<summary>Advanced</summary>

- Re-ingesting the same file is deduplicated via per-file SHA-256 (manifest-tracked).
- `--no-llm` files below ~1000 characters are **skipped** with `skipped (below 1000-char minimum; stub prevention)` — tiny files are never ingested.
- Without `--no-llm`, `ingest` calls an LLM; if none is reachable it **errors** — there is no silent fallback. See [Ingesting documents](ingesting.html) and [Troubleshooting](troubleshooting.html) (`llm-unavailable`).
- `--model` cannot be combined with `--no-llm`.
</details>

> [!NOTE]
> `OKFSMITH_API_KEY` is preferred over `--api-key` — the latter lands in your shell history.

---

## okfsmith sync

Incrementally sync a bundle with its source documents — only new, changed,
renamed, or deleted files are processed. This is the command to reach for
when your sources keep changing: run it after every edit instead of
re-ingesting everything.

```bash
okfsmith sync [OPTIONS] {bundle} {sources}...
```

```bash
# One-shot: ingest what's new, update what's changed, drop what's deleted
okfsmith sync ./kb ./docs --no-llm

# Keep watching: re-sync whenever sources change (Ctrl-C stops)
okfsmith sync ./kb ./docs --no-llm --watch --interval 10

# Preview without writing anything
okfsmith sync ./kb ./docs --no-llm --dry-run
```

Real output (the table and summary line are exactly what you see):

```text
                 Sync summary — kb
┏━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━┓
┃ File         ┃ Change ┃ Concepts ┃ Detail       ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━┩
│ src/guide.md │ added  │        1 │ 1 concept(s) │
│ src/notes.md │ added  │        1 │ 1 concept(s) │
└──────────────┴────────┴──────────┴──────────────┘
sync: 2 added, 0 updated, 0 renamed, 0 removed, 0 unchanged, 0 skipped, 0 failed → kb
```

### How it works

Each source file is fingerprinted with SHA-256 and recorded in
`<bundle>/.okfsmith/sync-state.json`. On every run, `sync` diffs the live
files against that state and classifies each file:

| Change | What happens |
|---|---|
| `added` | Ingested (LLM or `--no-llm` path, same as `ingest`). |
| `updated` | Old concepts are **replaced** — re-ingested under the same ids, never duplicated as `name-2`. |
| `renamed` | Detected by identical content hash; concepts keep their ids and history, only the `resource` provenance is updated. |
| `removed` | Concepts are deleted from the bundle. |
| `unchanged` | Skipped entirely — no parsing, no LLM calls. |

Additions are applied **before** deletions, so a rename or replace can never
leave the bundle momentarily empty. Writes are atomic and resumable: if a
sync is interrupted (Ctrl-C, power loss), the state is marked incomplete and
the next run picks up where it stopped — already-ingested concepts are
adopted, never duplicated.

A few safety rules worth knowing:

- **Pre-flight on updates.** If a changed file's new content would be
  skipped (unparseable, below the ~1000-char minimum, sectioning fails),
  the old concepts are kept instead of being wiped — you get a `skipped`
  row, not data loss.
- **Shared content is reference-counted.** Two identical files share one
  set of concepts; deleting one source only drops the concepts when the
  last file with that content is gone.
- **Deletions are scoped.** `sync ./kb ./docs` only ever removes concepts
  that came from `./docs` — other source trees are untouched.
- **Unreadable files fail per-file** (`failed` row) instead of aborting
  the whole run.

See [Syncing sources](syncing.html) for the full guide, including
`--watch` mode, `--format json` for scripts, and the state-file format.

---

## okfsmith list

List concepts in the bundle: id, type, title, trust tier.

```bash
okfsmith list [OPTIONS] {bundle}
```

```bash
okfsmith list ./kb

# JSON output only, for scripts
okfsmith list ./kb --format json | jq '.concepts[].id'

# Only human-reviewed concepts
okfsmith list ./kb --tier human-reviewed
```

Real output (trimmed — the real table had 18 rows):

```text
                      Concepts in kb
┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ ID                 ┃ Type  ┃ Title        ┃ Trust tier ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ big/first-bundle   │ Draft │ First Bundle │ unverified │
│ big/installation   │ Draft │ Installation │ unverified │
│ big/trust-tiers    │ Draft │ Trust Tiers  │ unverified │
│ ...                │ ...   │ ...          │ ...        │
└────────────────────┴───────┴──────────────┴────────────┘
18 concept(s)
```

### Common options {#list-options}
| Flag | What it does |
|---|---|
| `--format <text\|json>` | Output format (default `text`). |
| `--type <str>` | Only concepts of this type. |
| `--tier <str>` | Only this trust tier: `unverified`, `machine-confirmed`, `human-reviewed`. |

<details>
<summary>Advanced</summary>

- `--no-llm` ingested concepts are `type: Draft`, tier `unverified`.
- Concept ids look like `<file-slug>/<heading-slug>` (e.g. `big/first-bundle`); duplicates get `-2`, `-3` suffixes.
</details>

---

## okfsmith read

Print a concept: frontmatter as YAML, then the body.

```bash
okfsmith read [OPTIONS] {bundle} {concept_id}
```

```bash
okfsmith read ./kb big/first-bundle
okfsmith read ./kb big/first-bundle --format json
```

Real output (frontmatter, then body):

```yaml
---
type: Draft
title: First Bundle
description: Draft concept extracted without LLM; needs review
resource: big.md
generated:
  by: okfsmith/0.3.0
  at: '2026-09-26T12:18:20.100846+00:00'
status: draft
tags:
- draft
- no-llm
---
Run `okfsmith init ./kb` to create a new bundle, then ingest documents.
```

### Common options {#read-options}
| Flag | What it does |
|---|---|
| `--format <text\|json>` | Output format (default `text`). |

<details>
<summary>Advanced</summary>

- Unknown concept ids produce an error — `read` never fabricates a concept.
</details>

---

## okfsmith search

Full-text search over a bundle: id, title, description, tags, and body,
ranked with BM25 (stdlib-only, no new dependencies). The same engine powers
the MCP server's `search` tool and chat's `/search`, so all three rank
identically. See [Searching a bundle](../searching.md) for the query syntax
(phrases, exclusions, stemming) and scoring details.

```bash
okfsmith search [OPTIONS] {bundle} {query}
```

```bash
okfsmith search ./kb "knowledge graph"
okfsmith search ./kb "quarterly revenue" --tier human-reviewed -n 5
okfsmith search ./kb "api design" --format json
```

Results print as a `Score | ID | Type | Title | Tier` table (IDs never
truncated) plus an `N result(s)` line; zero results exit 0 with
`0 result(s)` and a stderr hint. An empty query is a usage error (exit 2).

### Common options {#search-options}
| Flag | What it does |
|---|---|
| `--limit <n>` / `-n` | Maximum results (default `10`, must be ≥ 1). |
| `--format <text\|json>` | Output format (default `text`). |
| `--type <str>` | Only concepts of this type. |
| `--tier <str>` | Only this trust tier: `unverified`, `machine-confirmed`, `human-reviewed`. |

> [!NOTE]
> **`okfsmith get` does not exist.** Typing it gives `No such command`
> (it even suggests *"Did you mean 'ingest'?"*). `get` lives in two other
> places:
>
> | What you want | Where to find it |
> |---|---|
> | **Read a concept from the terminal** | [`okfsmith read`](#okfsmith-read) — e.g. `okfsmith read ./kb big/installation` |
> | **Search interactively** | `/search <keywords>` inside [`okfsmith chat`](#okfsmith-chat) |
> | **Search/get as an agent** | The `search` and `get` **MCP tools** on the [`okfsmith mcp`](#okfsmith-mcp) server — see [MCP server](mcp.html) |

---

## okfsmith validate

Validate a bundle against OKF v0.2 (E001–E004 / W001–W015).

```bash
okfsmith validate [OPTIONS] {bundle}
```

```bash
okfsmith validate ./kb

# Treat warnings as failures (exit code != 0 if any warning exists)
okfsmith validate ./kb --strict

# Machine-readable, for CI
okfsmith validate ./kb --format json
```

Real output — a conformant bundle exits with code 0 (verified with `--strict` too):

```text
       Errors (0)
┏━━━━━━┳━━━━━━┳━━━━━━━━━┓
┃ Code ┃ File ┃ Message ┃
┡━━━━━━╇━━━━━━╇━━━━━━━━━┩
└──────┴──────┴━━━━━━━━━┘
      Warnings (0)
┏━━━━━━┳━━━━━━┳━━━━━━━━━┓
┃ Code ┃ File ┃ Message ┃
┡━━━━━━╇━━━━━━╇━━━━━━━━━┩
└──────┴──────┴━━━━━━━━━┘
Conformant: no errors, no warnings.
```

### Common options {#validate-options}
| Flag | What it does |
|---|---|
| `--format <text\|json>` | Output format (default `text`). |
| `--strict` | Treat warnings as failures. |

> [!TIP]
> What E001–E004 / W001–W006 mean and how to fix each one is on [Validation & error codes](validation.html).

---

## okfsmith graph

Show the concept link graph (nodes, edges, orphans, dead links).

```bash
okfsmith graph [OPTIONS] {bundle}
```

```bash
okfsmith graph ./kb

# Interactive viewer — writes <bundle>/viz.html by default
okfsmith graph ./kb --format html

# Mermaid diagram to stdout
okfsmith graph ./kb --format mermaid
```

Real output:

```text
18 concept(s), 0 link(s), 0 dead link(s).

Orphans (0):
  (none)

Dead links (0):
  (none)
```

### Common options {#graph-options}
| Flag | What it does |
|---|---|
| `--format <text\|json\|mermaid\|html>` | Output format (default `text`). `html` writes an interactive visualization — colorblind-safe palette, backlinks, search. |
| `--output <path>` | Write to a file instead of stdout. |

<details>
<summary>Advanced</summary>

- Default HTML output lands at `<bundle>/viz.html`.
- Mermaid output emits `flowchart LR` with one node per concept, e.g. `big_first_bundle["big/first-bundle — First Bundle"]`.
- Deterministic (`--no-llm`) sectioning produces zero inter-concept links, so a fresh bundle reports 0 links — that still validates fine.
</details>

> [!TIP]
> Everything the `viz.html` viewer can do (search, keyboard access, trust-by-shape legend) is on [Visualizing the knowledge graph](graph.html).

---

## okfsmith doctor

Check the environment: dependencies, extras, Ollama, writability.

```bash
okfsmith doctor
```

That's it — `doctor` takes no arguments, just run it whenever something looks wrong.

Real output (this machine: no Ollama, no `mcp`/`ocr` extras — trimmed):

```text
                                okfsmith doctor
┏━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Check          ┃ Status  ┃ Detail                                            ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ python >= 3.10 │ OK      │ 3.12.3                                            │
│ okfsmith       │ OK      │ 0.3.0                                             │
│ extra: mcp     │ MISSING │ Install the 'mcp' extra: pip install              │
│                │         │ 'okfsmith[mcp]' ...                               │
│ extra: ocr     │ MISSING │ Install the 'ocr' extra: pip install              │
│                │         │ 'okfsmith[ocr]' ...                               │
│ ollama         │ WARN    │ not reachable at http://localhost:11434 — use     │
│                │         │ --no-llm or set OPENAI_API_KEY                    │
│ llm api key    │ OK      │ set (hidden) (via OKFSMITH_API_KEY)               │
│ tmp writable   │ OK      │ /tmp                                              │
└────────────────┴━━━━━━━━━┴━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┘
```

> [!NOTE]
> `doctor` **never shows your API key** — it prints `set (hidden)` plus the source variable. Key statuses, `--provider` presets, and `OKFSMITH_*` env vars are documented on [Providers & API keys](providers.html).

`doctor` takes no options other than `--help`. If anything here looks wrong, head to [Troubleshooting](troubleshooting.html).

---

## okfsmith chat

Chat with a bundle in natural language (Claude Code / Gemini CLI style).

```bash
okfsmith chat [OPTIONS] [bundle]
```

The bundle is optional — if you omit it, the current directory is used (when it is a bundle).

```bash
# Extractive mode: keyword-matched answers, zero setup, no LLM
okfsmith chat ./kb --no-llm

# Generative answers via a hosted provider preset (needs OKFSMITH_API_KEY set)
okfsmith chat ./kb --provider openrouter --model anthropic/claude-sonnet-4

# Non-interactive: pipe slash commands
printf '/list\n/exit\n' | okfsmith chat ./kb
```

Real startup banner (ASCII logo first, then the version line):

```text
 ███  █   █ █████  ████ █   █ █████ █████ █   █
█   █ █  █  █     █     ██ ██   █     █   █   █
█   █ ███   ████   ███  █ █ █   █     █   █████
█   █ █  █  █         █ █   █   █     █   █   █
 ███  █   █ █     ████  █   █ █████   █   █   █
okfsmith chat v0.3.0
Bundle: kb (18 concepts) · extractive mode
Extractive mode — no LLM reachable. Answers are keyword-matched excerpts. Start
Ollama, set OKFSMITH_API_KEY + OKFSMITH_PROVIDER, or pass --provider, for
generative answers.

Tips for getting started:
  1. Ask questions about your documents.
  2. Type /help for chat commands.
  3. Type /ingest <path> to add more documents.

kb ›
```

### Common options {#chat-options}
| Flag | What it does |
|---|---|
| `--no-llm` | Extractive mode: keyword-matched excerpts, no LLM involved. |
| `--provider <str>` | Hosted provider preset (15 presets: `ollama`, `lmstudio`, `openai`, `groq`, `mistral`, `deepseek`, `openrouter`, `together`, `fireworks`, `deepinfra`, `anyscale`, `perplexity`, `xai`, `gemini`, `agentrouter`). |
| `--model <str>` | Model id for generative answers. |
| `--api-base <url>` | Any OpenAI-compatible endpoint (overrides `--provider`). |
| `--api-key <str>` | API key — prefer `OKFSMITH_API_KEY`, since `--api-key` lands in shell history. |

> [!TIP]
> Inside the REPL, `/help` lists every slash command: `/ingest`, `/list`, `/read`, `/search`, `/validate`, `/graph`, `/doctor`, `/model`, `/clear`, `/exit` (also `/quit`). `/exit` leaves with `Goodbye — your bundle is untouched.` — chat never modifies the bundle.

Full REPL walkthrough on [Interactive chat](chat.html); providers and keys on [Providers & API keys](providers.html).

---

## okfsmith mcp

Serve the bundle over MCP (Model Context Protocol) so agents can read it.

```bash
okfsmith mcp [OPTIONS] {bundle}
```

```bash
# Default stdio transport — for Claude Code / Desktop config
okfsmith mcp ./kb

# Server-sent events
okfsmith mcp ./kb --transport sse

# Streamable HTTP
okfsmith mcp ./kb --transport streamable-http
```

Requires the optional extra (flagged `MISSING` by `doctor`):

```bash
pip install "okfsmith[mcp]"
```

Without the extra, the command tells you exactly what to do:

```text
error [missing-extra]: The MCP server requires the 'mcp' extra: install it with `pip install "okfsmith[mcp]"`.
hint: Install it with: pip install "okfsmith[mcp]" (or pipx: pipx install "okfsmith[mcp]", or uvx: uvx --with "okfsmith[mcp]" okfsmith mcp ./kb)
```

### Common options {#mcp-options}
| Flag | What it does |
|---|---|
| `--transport <stdio\|sse\|streamable-http>` | Transport (default `stdio`). |

The server exposes five **MCP tools** — `index`, `list`, `search`, `get`, `neighbors`. These are tools for connected agents; `search` is also a CLI command (`okfsmith search`), while `get` remains MCP-only (the CLI analogue is `read`). Client config examples for Claude Code/Desktop, Cursor, Copilot, and Gemini are on [MCP server](mcp.html).

---

## Exit codes

| Exit | Meaning |
|---|---|
| `0` | Success — `validate` prints `Conformant: no errors, no warnings.` |
| `1` | Validation failed (errors, or warnings under `--strict`); or a general command error. |
| `2` | CLI usage error — e.g. `No such command` for `okfsmith get`. |

---

**Next:** [MCP server →](mcp.html) — bundle built, now serve it to agents.
