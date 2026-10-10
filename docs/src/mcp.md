---
title: MCP server
eyebrow: MCP
description: Serve a knowledge bundle to AI agents over the Model Context Protocol — eight read tools plus four governed write-back tools, stdio/SSE/streamable-HTTP transports, client config examples.
---

## MCP server

`okfsmith mcp` exposes your knowledge bundle as an **MCP (Model Context
Protocol) server** so AI agents — Claude Code, Claude Desktop, Cursor, Copilot,
Gemini — can search and read your bundle directly. Eight of the twelve tools
are read-only. The other four are *governed write-back* tools: an agent can
propose and write concepts, but every write lands at the `unverified` trust
tier, is stamped with provenance, must pass the bundle validator, and is
recorded in an append-only audit log. Human-reviewed concepts are never
silently overwritten (see [Governed write-back](#governed-write-back)).

> [!NOTE]
> `get` is an **MCP tool, not a CLI command** — there is no `okfsmith get`
> on the command line (the CLI analogue is `read`). `search` exists in both
> places: the [`okfsmith search`](cli.html#okfsmith-search) CLI command and
> the MCP `search` tool share the same BM25 engine, so they rank
> identically.

## Quick start

```bash
pip install "okfsmith[mcp]"
okfsmith mcp ./kb
```

The server starts on **stdio** (the standard transport: your MCP client
launches it as a subprocess) and exposes twelve tools. Pick one:

```bash
okfsmith mcp ./kb --transport stdio            # default
okfsmith mcp ./kb --transport sse              # Server-Sent Events
okfsmith mcp ./kb --transport streamable-http  # streamable HTTP
```

## The twelve tools

Tool outputs are compact markdown (not giant JSON) — designed as an agent's
reading UI. The intended flow is progressive disclosure: `index` → `search` →
`get`.

### Read tools

| Tool | What it does |
|---|---|
| `index` | Return the bundle's root `index.md` — the map of the whole knowledge base. Read this first to orient. |
| `list` | List every concept: id, type, trust tier, title. Optional `filter_type` narrows by concept type; `limit` caps rows. |
| `search` | BM25-ranked keyword search over concept id, title, description, tags, and body. Title matches rank highest, body lowest; results carry excerpts. |
| `get` | Read one concept in full: YAML frontmatter followed by its markdown body. Unknown ids produce an error — never fabricated content. |
| `neighbors` | Show a concept's link graph neighborhood: outgoing links and incoming backlinks, so agents can walk the knowledge graph. |
| `traverse` | Breadth-first neighborhood expansion over markdown links (depth ≤ 3, cycle-safe), with an optional `relation_filter` and currency-aware ordering — superseded concepts hidden by default. |
| `provenance` | Trace a concept's provenance chain: `sources[]` frontmatter → footnote references → the ingested-source manifest (`sync-state.json`) with source file and digest. |
| `diff` | Diff the bundle against another bundle directory (`against=`) or the `sync-state.json` snapshot: added / removed / changed concepts with body SHA-256. |

### Governed write-back tools

| Tool | What it does |
|---|---|
| `preview_write_concept` | Side-effect-free dry run of a create: shows the exact id, file path, frontmatter (with provenance block), and serialized content that `write_concept` would write. |
| `write_concept` | Create a new concept. Refuses if the id already exists (use `update_concept`); the write is atomic, so exactly one concurrent writer wins. |
| `update_concept` | Patch an existing concept's title, body, `sources`, or `links`; `dry_run=true` previews the diff without writing. |
| `audit_log` | Read the append-only write audit trail at `<bundle>/.okfsmith/audit.jsonl`. |

## Governed write-back

The four write-back tools exist so an agent can contribute to a bundle
without being able to quietly rewrite it:

- **Unverified by construction.** Every MCP write lands at the `unverified`
  trust tier; any `verified` markers in the input are stripped.
- **Validator-gated.** The bundle validator runs before a write commits;
  new validation errors refuse the write and roll it back. If the validator
  itself fails, the write fails closed.
- **Provenance-stamped.** Each write adds a frontmatter provenance entry
  (actor `mcp:<tool>`, UTC timestamp, input sources) and appends to the
  append-only audit log, readable via the `audit_log` tool.
- **Human review is protected.** A write never overwrites an existing
  concept (`write_concept` returns a structured error pointing at
  `update_concept`), and altering a human-reviewed concept requires an
  explicit `downgrade_trust=true`, which removes the `verified` marker and
  is recorded in provenance.
- **Atomic.** Creates claim the destination atomically (exactly one
  concurrent writer wins); a refused duplicate writes no audit entry.

If you want a strictly read-only server today, do not hand the agent a
writable bundle directory: serve a copy, or mount the bundle read-only at
the filesystem level. A future `--read-only` server flag is not currently
implemented.

A typical agent session looks like this:

1. `index` — "what's in this bundle?"
2. `search` with `"billing retries"` — ranked hits with excerpts
3. `get` with `billing/retries` — the full concept
4. `neighbors` with `billing/retries` — related concepts via links
5. `traverse` with `billing/retries`, `depth=2` — the wider neighborhood
6. `provenance` with `billing/retries` — where each claim came from

## Evidence budgets

The read tools accept three evidence-budget parameters so agents get bounded
evidence instead of unbounded context (the write-back tools take their own
arguments — see their docstrings via `preview_write_concept`):

| Parameter | Meaning |
|---|---|
| `max_chunks` | Max **items** (or 50-line text chunks) per response — default 10 for `search`/`traverse`, 50 elsewhere; hard cap 50. Notes (e.g. hidden-superseded counts) and `##` section headers sit outside the budget; `…[truncated, N more]` counts remaining *items* only. |
| `max_tokens` | Approximate output budget (chars ÷ 4). `None` (default) = unbounded; `0` = no item content; negative or unparseable values are treated as unbounded. Truncation cuts at whole-item boundaries, never mid-item, and is marked `…[truncated, N more]`. |
| `continuation_token` | Opaque paging cursor from a truncated response — pass it back for the next page. Tokens are result-offset cursors, not tied to a query. An invalid or out-of-range token returns a clean error, never a traceback. |

> [!NOTE]
> `provenance` and `diff` treat `sync-state.json` source paths as
> **untrusted manifest entries**: only paths inside the bundle root are
> hashed and displayed (bundle-relative, never absolute). Paths outside the
> root, `..` escapes, and symlinks are skipped with an
> `untrusted manifest` marker. `diff(against=…)` likewise guards its input —
> it rejects non-bundle directories and over-large directory trees before
> loading anything.

`search` and `traverse` are currency-aware: superseded concepts are hidden
by default (reported as a count); pass `include_superseded=True` to reveal
them. `traverse` depth is capped at 3.

## Claude Desktop config

Add okfsmith as an MCP server in your Claude Desktop config file
(`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "okfsmith-kb": {
      "command": "okfsmith",
      "args": ["mcp", "/absolute/path/to/kb"]
    }
  }
}
```

Restart Claude Desktop and the twelve tools (`index`, `list`, `search`, `get`,
`neighbors`, `traverse`, `provenance`, `diff`, `preview_write_concept`,
`write_concept`, `update_concept`, `audit_log`) appear in its tool list.

<details>
<summary>Advanced: other clients and transports</summary>

- **Claude Code** and **Cursor** accept the same stdio command shape
  (`okfsmith mcp <bundle>`); check their MCP server docs for the exact config
  file location.
- For **SSE** or **streamable-http** transports, point your client at the
  server's URL — the bundle is loaded once at server startup, and every tool
  call afterwards reads from the in-memory bundle, so responses are fast.
- The read tools back the interactive chat's `/search` and `/read`
  commands, so chat and MCP rank identically. Chat itself never writes to
  your bundle; only the MCP write-back tools can, under the governance
  above.

</details>

> [!TIP]
> The eight read tools cannot modify your bundle. The four write-back tools
> can create and update concepts, but only under governance: unverified
> tier, validator gate, provenance stamp, audit log, and no silent overwrite
> of human-reviewed work. Point the server at a bundle you care about only
> if that trade-off is acceptable — or serve a copy (see
> [Governed write-back](#governed-write-back)).

## Next →

[Troubleshooting →](troubleshooting.html)
