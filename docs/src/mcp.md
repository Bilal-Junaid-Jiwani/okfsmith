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
> `search` and `get` are **MCP tools, not CLI commands** — there is no
> `okfsmith search` or `okfsmith get` on the command line. The CLI analogues
> are `list` and `read` (see [search and get](cli.html#search-and-get)).

## Quick start

```bash
pip install "okfsmith[mcp]"
okfsmith mcp ./kb
```

The server starts on **stdio** (the standard transport: your MCP client
launches it as a subprocess) and exposes five tools. Pick one:

```bash
okfsmith mcp ./kb --transport stdio            # default
okfsmith mcp ./kb --transport sse              # Server-Sent Events
okfsmith mcp ./kb --transport streamable-http  # streamable HTTP
```

## The five tools

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

A typical agent session looks like this:

1. `index` — "what's in this bundle?"
2. `search` with `"billing retries"` — ranked hits with excerpts
3. `get` with `billing/retries` — the full concept
4. `neighbors` with `billing/retries` — related concepts via links

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

Restart Claude Desktop and the five tools (`index`, `list`, `search`, `get`,
`neighbors`) appear in its tool list.

<details>
<summary>Advanced: other clients and transports</summary>

- **Claude Code** and **Cursor** accept the same stdio command shape
  (`okfsmith mcp <bundle>`); check their MCP server docs for the exact config
  file location.
- For **SSE** or **streamable-http** transports, point your client at the
  server's URL — the bundle is loaded once at server startup, and every tool
  call afterwards reads from the in-memory bundle, so responses are fast.
- The same five tools back the interactive chat's `/search` and `/read`
  commands, so chat and MCP rank identically.

</details>

> [!TIP]
> The server is fully **read-only** — there is no tool that writes, edits, or
> deletes concepts. You can point it at a bundle you care about without fear.

## Next →

[Troubleshooting →](troubleshooting.html)
