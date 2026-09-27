---
title: MCP server
eyebrow: MCP
description: Serve a knowledge bundle to AI agents over the Model Context Protocol — read-only tools, stdio/SSE/streamable-HTTP transports, client config examples.
---

## MCP server

`okfsmith mcp` exposes your knowledge bundle as a **read-only MCP (Model
Context Protocol) server** so AI agents — Claude Code, Claude Desktop, Cursor,
Copilot, Gemini — can search and read your bundle directly. Agents get live
answers; your bundle is never modified.

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
launches it as a subprocess) and exposes eight tools. Pick one:

```bash
okfsmith mcp ./kb --transport stdio            # default
okfsmith mcp ./kb --transport sse              # Server-Sent Events
okfsmith mcp ./kb --transport streamable-http  # streamable HTTP
```

## The eight tools

Tool outputs are compact markdown (not giant JSON) — designed as an agent's
reading UI. The intended flow is progressive disclosure: `index` → `search` →
`get`.

| Tool | What it does |
|---|---|
| `index` | Return the bundle's root `index.md` — the map of the whole knowledge base. Read this first to orient. |
| `list` | List every concept: id, type, trust tier, title. Optional `filter_type` narrows by concept type; `limit` caps rows. |
| `search` | Keyword-search concepts by id, title, description, tags, and body. Case-insensitive; title matches rank highest, body lowest. |
| `get` | Read one concept in full: YAML frontmatter followed by its markdown body. Unknown ids produce an error — never fabricated content. |
| `neighbors` | Show a concept's link graph neighborhood: outgoing links and incoming backlinks, so agents can walk the knowledge graph. |
| `traverse` | Breadth-first neighborhood expansion over markdown links (depth ≤ 3, cycle-safe), with an optional `relation_filter` and currency-aware ordering — superseded concepts hidden by default. |
| `provenance` | Trace a concept's provenance chain: `sources[]` frontmatter → footnote references → the ingested-source manifest (`sync-state.json`) with source file and digest. |
| `diff` | Diff the bundle against another bundle directory (`against=`) or the `sync-state.json` snapshot: added / removed / changed concepts with body SHA-256. |

A typical agent session looks like this:

1. `index` — "what's in this bundle?"
2. `search` with `"billing retries"` — ranked hits with excerpts
3. `get` with `billing/retries` — the full concept
4. `neighbors` with `billing/retries` — related concepts via links
5. `traverse` with `billing/retries`, `depth=2` — the wider neighborhood
6. `provenance` with `billing/retries` — where each claim came from

## Evidence budgets

Every tool accepts three evidence-budget parameters so agents get bounded
evidence instead of unbounded context:

| Parameter | Meaning |
|---|---|
| `max_chunks` | Max items (or 50-line text chunks) per response — default 10 for `search`/`traverse`, 50 elsewhere; hard cap 50. |
| `max_tokens` | Approximate output budget (chars ÷ 4). `None` (default) = unbounded. Truncation cuts at whole-item boundaries, never mid-item, and is marked `…[truncated, N more]`. |
| `continuation_token` | Opaque paging token from a truncated response — pass it back for the next page. An invalid token returns a clean error, never a traceback. |

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

Restart Claude Desktop and the eight tools (`index`, `list`, `search`, `get`,
`neighbors`, `traverse`, `provenance`, `diff`) appear in its tool list.

<details>
<summary>Advanced: other clients and transports</summary>

- **Claude Code** and **Cursor** accept the same stdio command shape
  (`okfsmith mcp <bundle>`); check their MCP server docs for the exact config
  file location.
- For **SSE** or **streamable-http** transports, point your client at the
  server's URL — the bundle is loaded once at server startup, and every tool
  call afterwards reads from the in-memory bundle, so responses are fast.
- The same eight tools back the interactive chat's `/search` and `/read`
  commands, so chat and MCP rank identically.

</details>

> [!TIP]
> The server is fully **read-only** — there is no tool that writes, edits, or
> deletes concepts. You can point it at a bundle you care about without fear.

## Next →

[Troubleshooting →](troubleshooting.html)
