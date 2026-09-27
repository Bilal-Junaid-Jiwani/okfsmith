---
title: Agent skill pack
eyebrow: User guide
description: The okfsmith-build skill pack teaches AI agents the init-ingest-validate-serve loop for OKF bundles, with references and a stdlib validator.
---

## Agent skill pack

The **okfsmith-build** skill pack teaches an AI agent (Claude Code, Cursor,
Copilot, Gemini CLI, or any agent with skill support) how to build OKF v0.2
knowledge bundles with okfsmith — the full loop: scaffold → ingest →
validate → serve.

> [!NOTE]
> This page is for **agent builders and power users** who want an agent to do
> the bundle-building work. If you're a human following the beginner flow,
> start at [Quickstart](quickstart.html) instead.

## What it is

An agent skill is a folder of instructions an agent loads when it needs a
capability. `okfsmith-build` covers:

- **When to use it** — converting PDFs, wiki dumps, Notion exports, and
  markdown collections into OKF v0.2 bundles; validating bundles against the
  OKF §11 conformance rules; serving finished bundles over MCP.
- **When NOT to use it** — code-graph extraction from repos (that's a
  code-graph tool's job), executing attested computations, already-clean
  markdown pipelines, or general document search.
- **The workflow** — `init` → `ingest` → `validate` → `mcp`, with a decision
  table for situations like scanned-image PDFs (escalate parsing) or existing
  bundles (validate only).
- **The gotchas** — spec subtleties an agent must not get wrong: only `type`
  is required on a concept, broken links are warnings not errors, the `human:`
  prefix drives trust tiers, concept IDs are paths minus `.md`, and more.

## Where it lives

In the okfsmith repo at `skills/okfsmith-build/`:

```
skills/okfsmith-build/
├── SKILL.md                  # the skill: workflow, decision table, gotchas
├── references/
│   ├── okf-v02-cheatsheet.md # condensed v0.2 frontmatter/index/log/linking rules
│   ├── parsing-tiers.md      # which parser for which input
│   └── mcp-recipes.md        # client configs to attach `okfsmith mcp`
└── scripts/
    └── validate.py           # stdlib-only OKF §11 validator
```

`scripts/validate.py` is the standout: a **stdlib-only validator** that works
even without okfsmith installed (uses `okfsmith.validate.check` when the
package is present, otherwise a minimal E001–E004 check). It emits
machine-readable JSON (`{bundle, engine, conformant, errors[], warnings[]}`)
with exit codes 0 = conformant, 1 = errors, 2 = usage/IO failure — perfect for
an agent's verification step.

## How agents use it

An agent with the skill installed follows this loop:

```bash
# 1. init — scaffold a new OKF v0.2 bundle
okfsmith init ./kb

# 2. ingest — parse sources → extract concepts
#    deterministic sectioning: no API key, works offline
okfsmith ingest ./kb ./docs --no-llm

# 3. validate — check OKF §11 conformance (hard rules + advisory lints)
okfsmith validate ./kb
# or, without okfsmith installed:
python3 scripts/validate.py ./kb

# 4. mcp — serve the bundle to other agents over stdio
okfsmith mcp ./kb
# tools exposed: search, get, list, neighbors, index, traverse, provenance, diff
```

Zip archives and Notion exports ingest the same way — e.g.
`okfsmith ingest ./kb ./exports/notion-export.zip --no-llm`.
Add `--recursive` when a source is a directory with subdirectories.

Newly ingested concepts land as `unverified`; extraction Pass 2 promotes them
to `machine-confirmed`; a human stamping `verified:` promotes them to
`human-reviewed`.

### Trigger phrases

The skill fires on requests like: *"build a knowledge bundle from these
docs"*, *"convert this PDF collection to OKF"*, *"validate my bundle"*,
*"ingest these wiki dumps"*. Keywords: `okf`, `knowledge bundle`, `convert
docs to OKF`, `ingest PDF to knowledge base`, `bundle validator`, `open
knowledge format`.

<details>
<summary>Advanced: installing the skill</summary>

How the skill gets into an agent depends on the agent. For Claude Code, skills
live in `~/.claude/skills/` (personal) or `<project>/.claude/skills/`
(project); for other agents, see their skill/plugin docs. Copy or symlink the
whole `skills/okfsmith-build/` directory — the skill is self-contained, and
`references/` is loaded one level deep on demand. Nothing needs to be
installed on PyPI for the skill itself; the agent needs `okfsmith`
(`pip install okfsmith`) for the `init`/`ingest`/`validate`/`mcp` commands.

For LLM-based extraction instead of `--no-llm`, the agent drops the
`--no-llm` flag and configures a provider (see [Providers](providers.html)) —
`ingest` then calls the model, and errors if none is reachable.

</details>

> [!TIP]
> After an agent builds and serves a bundle, read it back with the
> [MCP server](mcp.html) or explore it in the [chat REPL](chat.html).

## Next →

[FAQ →](faq.html)
