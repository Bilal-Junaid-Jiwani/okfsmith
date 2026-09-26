# Commands

The bundle is always the **first positional argument**. Run any command with
`--help` for its full options.

```bash
okfsmith init BUNDLE [--force] [--yes]
okfsmith ingest BUNDLE SOURCE... [--recursive] [--no-llm] [--model NAME]
                                 [--provider NAME] [--api-base URL] [--api-key KEY]
                                 [--dry-run] [--quiet]
okfsmith validate BUNDLE [--format text|json] [--strict]
okfsmith list BUNDLE [--format text|json] [--tier TIER]
okfsmith read BUNDLE CONCEPT_ID [--format text|json]
okfsmith graph BUNDLE [--format text|json|mermaid|html] [--output FILE]
okfsmith mcp BUNDLE [--transport stdio|sse|streamable-http]
okfsmith chat [BUNDLE] [--model NAME] [--provider NAME] [--api-base URL]
                [--api-key KEY] [--no-llm]
okfsmith doctor
```

## init — scaffold a bundle

```bash
okfsmith init ./kb
```

Creates `index.md` (manifest) and `log.md` (activity log). Refuses to touch a
non-empty directory unless `--force` is given; `--force` asks for
confirmation unless `--yes` is passed.

## ingest — add documents

```bash
okfsmith ingest ./kb paper.pdf notes/ --no-llm
okfsmith ingest ./kb dump/ --recursive --no-llm
okfsmith ingest ./kb paper.pdf --dry-run     # parse only, write nothing
okfsmith ingest ./kb paper.pdf --quiet       # one-line summary, no tables
```

- Multiple sources per run; directories are scanned non-recursively unless
  `--recursive` is given.
- Sources are SHA-256 fingerprinted: already-ingested files are skipped.
- `--no-llm` writes one draft concept per section (fast, offline).
  Without it, okfsmith uses an LLM (Ollama by default) for richer extraction —
  see [LLM & no-LLM](llm.md).
- `--model` and `--no-llm` together are a usage error (exit 2) — as are
  `--provider`, `--api-base`, and `--api-key` with `--no-llm`.
- Any hosted model works: `--provider openrouter --model
  anthropic/claude-sonnet-4` (one key, hundreds of models), or pick from
  the 15 presets (`groq`, `mistral`, `deepseek`, `together`, `fireworks`,
  `deepinfra`, `anyscale`, `perplexity`, `xai`, `gemini`, `openai`,
  `agentrouter`, `lmstudio`, `ollama`) — key in `OKFSMITH_API_KEY`
  (`AGENTROUTER_API_KEY` for `agentrouter`). See [LLM & no-LLM](llm.md).
- Failures are reported per file; a summary table shows SHA-256, concept
  count, and status for each input. If *all* inputs fail, the exit code is 1.

## validate — check OKF v0.2 conformance

```bash
okfsmith validate ./kb
okfsmith validate ./kb --format json   # {"status": ..., "concepts": N, ...}
okfsmith validate ./kb --strict        # warnings also fail (exit 1)
```

Exit 0 means conformant. `--format json` emits a machine-readable report with
top-level `status`, `concepts`, `error_count`, and `warning_count`. See
[Validation & error codes](validation.md) for the rule list.

## list — show concepts

```bash
okfsmith list ./kb
okfsmith list ./kb --tier human-reviewed
okfsmith list ./kb --format json
```

`--tier` accepts `unverified`, `machine-confirmed`, or `human-reviewed`
(anything else is a usage error, exit 2).

## read — print one concept

```bash
okfsmith read ./kb finance/revenue
okfsmith read ./kb finance/revenue --format json
```

Concept ids are bundle-relative paths without the `.md` suffix.

## graph — links between concepts

```bash
okfsmith graph ./kb                    # text summary: counts, orphans, dead links
okfsmith graph ./kb --format json      # {"nodes": [...], "adjacency": {...}}
okfsmith graph ./kb --format mermaid   # flowchart LR diagram
okfsmith graph ./kb --format html      # self-contained viz.html (offline)
okfsmith graph ./kb --format html --output ./site/graph.html
```

The HTML viewer: nodes colored by concept type (colorblind-safe palette),
shaped by trust tier; click for details with backlinks; search with match
count; keyboard navigable; includes a screen-reader concept list.

## mcp — serve a bundle to agents

```bash
okfsmith mcp ./kb                              # stdio (for Claude/Cursor/...)
okfsmith mcp ./kb --transport streamable-http  # HTTP transport
```

Needs the `mcp` extra (`pip install "okfsmith[mcp]"`). Tools exposed:
`index`, `list`, `search`, `get`, `neighbors`. See [MCP](mcp.md) for client
configuration.

## doctor — check your setup

```bash
okfsmith doctor
```

Reports Python version, core dependencies, optional extras (with the exact
install command for anything missing), Ollama reachability, and temp-dir
writability.

## chat — interactive Q&A

```bash
okfsmith chat ./kb                 # REPL; Ollama if reachable, else extractive
okfsmith chat ./kb --no-llm        # extractive mode: concept excerpts, no LLM
okfsmith chat ./kb --model qwen3:8b
okfsmith chat ./kb --provider openrouter --model anthropic/claude-sonnet-4
printf '/list\n/exit\n' | okfsmith chat ./kb   # scriptable via stdin
```

Ask questions in plain language; answers carry `[concept-id]` citations and a
Sources footer. Follow-ups ("tell me more", "uska source kya hai") resolve
against the recent conversation. Slash commands: `/help`, `/ingest <path>`
(`--recursive` supported), `/list`, `/read <id>`, `/search <keywords>`,
`/validate`, `/graph`, `/doctor`, `/model [name]`, `/clear`, `/exit` (`/quit`
too). Line history persists at `~/.okfsmith/history`; Ctrl-C cancels the
current input, Ctrl-D quits. BUNDLE defaults to the current directory when it
is a bundle. Hallucinated citations are stripped — every cited concept is a
real bundle concept.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | success (for `validate`: conformant) |
| 1 | expected failure — message starts with `error [CODE]:`, e.g. `error [bundle-not-found]:` |
| 2 | usage error — bad flags, invalid `--format`/`--tier`/`--transport`, conflicting options |

Expected failures never print tracebacks. JSON-output commands emit a JSON
error object (`{"status": "error", "code": ..., "message": ...}`) when
`--format json` was requested.
