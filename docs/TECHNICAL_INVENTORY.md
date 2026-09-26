# okfsmith — Technical Inventory (ground truth for content writers)

All facts below were verified on **2026-09-26** by running the real CLI
(`~/workspace/projects/okfsmith/.venv/bin/python -m okfsmith`, version **0.2.0**)
in a scratch directory. Nothing here is invented. All examples were executed;
their outputs are real and trimmed to essentials.

**Global note:** the CLI is a Typer app. `okfsmith --help` shows global options
`--version`, `--install-completion`, `--show-completion`, `--help`.
**There is no standalone `completions` command** — shell completion is installed
via `okfsmith --install-completion` / previewed with `okfsmith --show-completion`.

## 1. Full command list (exact help text from `okfsmith --help`)

| Command | Exact one-line description (verbatim) |
|---|---|
| `init` | Create a new, empty OKF bundle in BUNDLE. |
| `doctor` | Check the environment: dependencies, extras, Ollama, writability. |
| `ingest` | Ingest documents into BUNDLE as draft concepts. |
| `validate` | Validate a bundle against OKF v0.2 (E001–E004 / W001–W015). |
| `list` | List concepts in the bundle: id, type, title, trust tier. |
| `read` | Print a concept: frontmatter as YAML, then the body. |
| `graph` | Show the concept link graph (nodes, edges, orphans, dead links). |
| `mcp` | Serve the bundle over MCP (Model Context Protocol). |
| `chat` | Chat with a bundle in natural language (Claude Code / Gemini CLI style). |

**Commands that do NOT exist** (CLI answers `No such command`):
- `search` — does not exist as a CLI command. `/search` exists only as a *chat
  slash command* (keyword-search concepts inside the REPL); `search` is also an
  *MCP tool* exposed by the `mcp` server, not a CLI subcommand.
- `get` — does not exist (`get` is an MCP tool; the CLI equivalent is `read`).
  The CLI even suggests `Did you mean 'ingest'?`.
- `completions` — does not exist; use the global `--install-completion` /
  `--show-completion` flags instead.

## 2. Per-command syntax, beginner flags, and real runnable examples

Simplest working example first for each command. All examples below were run in
`/tmp/okfdoc` (scratch directory, safe to repeat).

### init — Create a new, empty OKF bundle in BUNDLE.

Syntax: `okfsmith init [OPTIONS] {bundle}`

Beginner-friendly flags: `--force` (scaffold even if the bundle exists and is
non-empty), `--yes`/`-y` (answer 'yes' to the `--force` confirmation prompt,
for non-interactive use).

Real example + output:
```
$ okfsmith init ./kb
Initialized OKF bundle in kb
  index: /tmp/okfdoc/kb/index.md
  log:   /tmp/okfdoc/kb/log.md
Next: add sources with 'okfsmith ingest kb <file-or-dir> --no-llm'.
```
Ground truth: `init` creates exactly two files — `index.md` and `log.md` —
inside the bundle directory. Nothing else is scaffolded.

### ingest — Ingest documents into BUNDLE as draft concepts.

Syntax: `okfsmith ingest [OPTIONS] {bundle} {sources}...`

Beginner-friendly flags: `--no-llm` (deterministic sectioning, no LLM needed —
recommended first path), `--dry-run` (parse and plan only; write nothing),
`--quiet`/`-q` (only warnings, errors, and the final summary line),
`--recursive` (recurse into subdirectories when a SOURCE is a directory).

Real example + output (after writing a ~1.7 KB `big.md`):
```
$ okfsmith ingest ./kb big.md --no-llm
    Ingest summary — sectioning (no LLM)
┏━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━┓
┃ File   ┃ SHA-256      ┃ Concepts ┃ Status ┃
┡━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━┩
│ big.md │ 34a0dca378f8 │       18 │ ok     │
└────────┴──────────────┴──────────┴────────┘
ingested 18 concept(s) from 1 file(s) into kb
```
Ground truth: `--no-llm` files below ~1000 characters are skipped with
`skipped (below 1000-char minimum; stub prevention)`. Re-ingesting the same
file is deduplicated via per-file SHA-256 (manifest-tracked). LLM extraction is
the default path when `--no-llm` is NOT passed; if no LLM is reachable, expect
an error, not silent fallback.

### list — List concepts in the bundle: id, type, title, trust tier.

Syntax: `okfsmith list [OPTIONS] {bundle}`

Beginner-friendly flags: `--format <text|json>` (default text),
`--type <str>` (only concepts of this type), `--tier <str>` (only this trust
tier: `unverified`, `machine-confirmed`, `human-reviewed`).

Real example + output:
```
$ okfsmith list ./kb
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
JSON shape (verified): `{"concepts": [{"id", "type", "title", "tier"}]}`.
Ground truth: `--no-llm` ingested concepts are `type: Draft`, trust tier
`unverified`, ids look like `<file-slug>/<heading-slug>` (e.g.
`big/first-bundle`, duplicates get `-2`, `-3` suffixes).

### read — Print a concept: frontmatter as YAML, then the body.

Syntax: `okfsmith read [OPTIONS] {bundle} {concept_id}`

Beginner-friendly flags: `--format <text|json>` (default text).

Real example + output:
```
$ okfsmith read ./kb big/first-bundle
---
type: Draft
title: First Bundle
description: Draft concept extracted without LLM; needs review
resource: big.md
generated:
  by: okfsmith/0.2.0
  at: '2026-09-26T12:18:20.100846+00:00'
status: draft
tags:
- draft
- no-llm
---
Run `okfsmith init ./kb` to create a new bundle, then ingest documents.
```
Ground truth: concept id format is `file/heading` (e.g. `finance/revenue` in
the help examples). Unknown ids produce an error — read never fabricates.

### validate — Validate a bundle against OKF v0.2 (E001–E004 / W001–W015).

Syntax: `okfsmith validate [OPTIONS] {bundle}`

Beginner-friendly flags: `--format <text|json>` (default text),
`--strict` (treat warnings as failures).

Real example + output:
```
$ okfsmith validate ./kb
       Errors (0)
┏━━━━━━┳━━━━━━┳━━━━━━━━━┓
┃ Code ┃ File ┃ Message ┃
┡━━━━━━╇━━━━━━╇━━━━━━━━━┩
└──────┴──────┴─────────┘
      Warnings (0)
┏━━━━━━┳━━━━━━┳━━━━━━━━━┓
┃ Code ┃ File ┃ Message ┃
┡━━━━━━╇━━━━━━╇━━━━━━━━━┩
└──────┴──────┴─────────┘
Conformant: no errors, no warnings.
```
Ground truth: a conformant bundle exits with code 0 (verified with
`--strict` too). README's table ("exit 0 = conformant") matches real behavior.

### graph — Show the concept link graph (nodes, edges, orphans, dead links).

Syntax: `okfsmith graph [OPTIONS] {bundle}`

Beginner-friendly flags: `--format <text|json|mermaid|html>` (default text;
`html` writes an interactive visualization — colorblind-safe palette, backlinks,
search — default output `<bundle>/viz.html`), `--output <path>` (write to a
file instead of stdout).

Real example + output:
```
$ okfsmith graph ./kb
18 concept(s), 0 link(s), 0 dead link(s).

Orphans (0):
  (none)

Dead links (0):
  (none)
```
Mermaid preview (verified): emits `flowchart LR` with one node per concept,
e.g. `big_first_bundle["big/first-bundle — First Bundle"]`.
Ground truth: deterministic sectioning produces zero inter-concept links, so a
fresh `--no-llm` bundle reports 0 links/orphans/dead links and still validates.

### doctor — Check the environment: dependencies, extras, Ollama, writability.

Syntax: `okfsmith doctor` (no arguments, no options other than `--help`).

Real example + output (this machine, no Ollama, no `mcp`/`ocr` extras):
```
                                okfsmith doctor
┏━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Check          ┃ Status  ┃ Detail                                            ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ python >= 3.10 │ OK      │ 3.12.3                                            │
│ okfsmith       │ OK      │ 0.2.0                                             │
│ typer          │ OK      │ 0.27.2                                            │
│ pyyaml         │ OK      │ 6.0.3                                             │
│ rich           │ OK      │ 15.0.0                                            │
│ httpx          │ OK      │ 0.28.1                                            │
│ liteparse      │ OK      │ 2.14.7                                            │
│ extra: office  │ OK      │ markitdown                                        │
│ extra: mcp     │ MISSING │ Install the 'mcp' extra: pip install              │
│                │         │ 'okfsmith[mcp]' ...                               │
│ extra: ocr     │ MISSING │ Install the 'ocr' extra: pip install              │
│                │         │ 'okfsmith[ocr]' ...                               │
│ extra: test    │ OK      │ pytest                                            │
│ ollama         │ WARN    │ not reachable at http://localhost:11434 — use     │
│                │         │ --no-llm or set OPENAI_API_KEY                    │
│ llm provider   │ OK      │ ollama                                            │
│ llm base URL   │ OK      │ http://localhost:11434                            │
│ llm model      │ OK      │ qwen3:8b                                          │
│ llm api key    │ MISSING │ not needed for local Ollama; set OKFSMITH_API_KEY │
│                │         │ for hosted providers                              │
│ tmp writable   │ OK      │ /tmp                                              │
└────────────────┴━━━━━━━━━┴━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┘
```
Ground truth on key masking (verified with a placeholder key):
```
│ llm api key    │ OK      │ set (hidden) (via OKFSMITH_API_KEY)               │
```
Keys are **never echoed** — doctor shows only `set (hidden)` plus the source.

### chat — Chat with a bundle in natural language (Claude Code / Gemini CLI style).

Syntax: `okfsmith chat [OPTIONS] [bundle]` (bundle optional — defaults to the
current directory if it is a bundle).

Beginner-friendly flags: `--no-llm` (extractive mode: keyword-matched excerpts,
no LLM involved — works with zero setup), `--provider <str>` (hosted preset),
`--model <str>` (model id for generative answers).

See §3 for the full startup banner. Non-interactive usage works via piped
stdin (examples ship in the CLI's own help): `printf '/list\n/exit\n' |
okfsmith chat ./kb`.

### mcp — Serve the bundle over MCP (Model Context Protocol).

Syntax: `okfsmith mcp [OPTIONS] {bundle}`

Beginner-friendly flags: `--transport <stdio|sse|streamable-http>` (default
`stdio`).

Real example + output (without the optional `mcp` extra installed):
```
$ okfsmith mcp ./kb
error [missing-extra]: The MCP server requires the 'mcp' extra: install it with `pip install "okfsmith[mcp]"`.
hint: Install it with: pip install "okfsmith[mcp]" (or pipx: pipx install "okfsmith[mcp]", or uvx: uvx --with "okfsmith[mcp]" okfsmith mcp ./kb)
```
Ground truth: `mcp` needs `pip install "okfsmith[mcp]"` (flagged MISSING by
`doctor`). When available, the server exposes tools `index`, `list`, `search`,
`get`, `neighbors` — these are MCP tools, **not** CLI commands (see §5).

## 3. The chat UI — exact startup banner (verified via `printf '/help\n/exit\n' | okfsmith chat ./kb --no-llm`)

```
 ███  █   █ █████  ████ █   █ █████ █████ █   █
█   █ █  █  █     █     ██ ██   █     █   █   █
█   █ ███   ████   ███  █ █ █   █     █   █████
█   █ █  █  █         █ █   █   █     █   █   █
 ███  █   █ █     ████  █   █ █████   █   █   █
okfsmith chat v0.2.0
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
Ground truth for writers:
- **ASCII logo: yes.** The "OKF" block-letter logo prints first, then
  `okfsmith chat v0.2.0` (version line).
- The bundle line reads `Bundle: <name> (<N> concepts) · extractive mode`
  when no LLM is reachable (or `--no-llm` was passed).
- In extractive mode a two-line explainer tells the user how to get generative
  answers (start Ollama, set `OKFSMITH_API_KEY` + `OKFSMITH_PROVIDER`, or pass
  `--provider`).
- Three numbered tips follow, then the prompt `kb › ` (bundle name + ` › `).
- `/help` prints a table of slash commands; `/exit` (or `/quit`) leaves with
  `Goodbye — your bundle is untouched.`

Verified `/help` slash commands inside chat:

| Command | What it does |
|---|---|
| `/help` | Show this table. |
| `/ingest <path> [--recursive]` | Ingest a file or directory into the bundle. |
| `/list` | List concepts in the bundle. |
| `/read <id>` | Print a concept in full. |
| `/search <keywords>` | Keyword-search concepts. |
| `/validate` | Validate the bundle against OKF v0.2. |
| `/graph` | Show the concept link graph. |
| `/doctor` | Check the environment. |
| `/model` | Show or switch the LLM backend/model/provider. |
| `/clear` | Clear the screen and conversation history. |
| `/exit` | Leave the chat (/quit works too). |

Real extractive-mode Q&A (piped): a question prints a `✦ Matches for: ...`
table (Concept / Trust tier / Excerpt) and then:
`Extractive mode: excerpts above, no generative summary. Use /read <id> for the full concept.`

## 4. Provider system and environment variables

`--provider` presets accepted by `chat` and `ingest` (from
`--help` and `src/okfsmith/extract/llm.py`, 15 presets):
`ollama`, `lmstudio`, `openai`, `groq`, `mistral`, `deepseek`, `openrouter`,
`together`, `fireworks`, `deepinfra`, `anyscale`, `perplexity`, `xai`, `gemini`,
`agentrouter`.

Relevant base URLs (canonical, from source): `ollama → http://localhost:11434/v1`,
`lmstudio → http://localhost:1234/v1`, `openrouter → https://openrouter.ai/api/v1`,
`agentrouter → https://agentrouter.org/v1`, `gemini → https://generativelanguage.googleapis.com/v1beta/openai`, etc.
Any other endpoint (Azure OpenAI, self-hosted vLLM / llama.cpp, any compat
proxy) works via `--api-base` / `OKFSMITH_API_BASE` — `--api-base` overrides
`--provider`.

Environment variables (verified in source and help text):
- `OKFSMITH_API_KEY` — API key for the hosted endpoint (preferred over
  `--api-key`, which lands in shell history).
- `OKFSMITH_PROVIDER` — provider preset name.
- `OKFSMITH_API_BASE` / `OKFSMITH_BASE_URL` — custom OpenAI-compatible base URL.
- `OKFSMITH_MODEL` — default model name (overridden by `--model`).
- `AGENTROUTER_API_KEY` — honored when the resolved provider is `agentrouter`.
- `OPENAI_API_KEY` — legacy fallback for hosted OpenAI-compatible endpoints.

Help-text examples ship the literal placeholder line `export
OKFSMITH_API_KEY=<redacted>` (that is the actual text in the CLI's `--help`;
it is not a real key). Use `your-key-here` in docs.

Key masking: confirmed — `doctor` prints `set (hidden)` and never echoes the
value. The `--help` text also explicitly warns `--api-key` lands in shell
history.

Other ground truth: Anthropic's native API is NOT supported directly (not
OpenAI-compatible) — the chat help says to use a compat proxy or the
`openrouter` preset. `--model` cannot be combined with `--no-llm` (raises a
parameter error).

## 5. What the CLI does NOT do (no fake features) and README cross-check

- **No `search` CLI command.** Writers must not document `okfsmith search`.
  Search exists as (a) the `/search` chat slash command, (b) an MCP tool.
- **No `get` CLI command.** The CLI equivalent is `read`.
- **No `completions` command.** Use `--install-completion` / `--show-completion`.
- **No delete/remove/update/export/edit commands.** There is no way to delete
  a concept, rename, or export the bundle via the CLI. Chat promises
  `Goodbye — your bundle is untouched` — chat never modifies the bundle.
- **No direct Anthropic provider.** No `--provider anthropic`; use openrouter.
- **`init` creates only `index.md` + `log.md`** — not a template tree or
  config files.
- **Ingest has a ~1000-char minimum per file in `--no-llm` mode** — tiny files
  are skipped, not ingested (stub prevention).
- **LLM extraction is the default ingest path** — `ingest` without `--no-llm`
  calls an LLM; with no LLM reachable it errors rather than falling back.
- **README.md / docs/commands.md cross-check: PASS.** Both describe exactly
  the real command set; `search`/`get` mentions refer to MCP tools and chat
  slash commands, which is accurate. The README banner example
  (`okfsmith chat v0.2.0`, ASCII logo) matches the real banner. The
  `--format html` graph default output `<bundle>/viz.html` is accurate per
  `--help`. No contradictions found.
