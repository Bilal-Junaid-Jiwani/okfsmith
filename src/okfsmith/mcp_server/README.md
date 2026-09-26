# okfsmith MCP server

Expose an OKF v0.2 knowledge bundle to AI agents over the
[Model Context Protocol](https://modelcontextprotocol.io/) (stdio transport
by default). The bundle is loaded **once** at startup and served for as many
tool calls as the client makes. All tools are **read-only** — nothing here
can modify the bundle.

## Install

FastMCP is an optional extra so the base install stays light:

```bash
pip install "okfsmith[mcp]"
```

## Tools

| Tool | What it does |
|---|---|
| `index()` | Root `index.md` — the map of the whole knowledge base (start here) |
| `list(filter_type="", limit=50)` | Concept inventory: id, type, trust tier, title; optional type filter |
| `search(query, limit=10)` | Keyword search over id / title / description / tags / body, ranked by field |
| `get(concept_id)` | Full concept: YAML frontmatter + markdown body |
| `neighbors(concept_id)` | Outgoing links + incoming backlinks, with the link text as the relation note |

Tool outputs are compact markdown (id, type, trust tier, title, one-line
description), designed for progressive disclosure: `index` → `search`/`list`
→ `get` → `neighbors`. Missing ids return a clean `Error: ...` string, never
an exception.

## Client configuration

Add this to your MCP client's server config (e.g. Claude Code's
`~/.claude.json`, Cursor, or any MCP host):

```json
{
  "mcpServers": {
    "okfsmith": {
      "command": "uvx",
      "args": ["okfsmith[mcp]", "mcp", "<path-to-your-bundle>"]
    }
  }
}
```

Or, if okfsmith is already installed in the current environment:

```json
{
  "mcpServers": {
    "okfsmith": {
      "command": "okfsmith",
      "args": ["mcp", "./kb"]
    }
  }
}
```

The `mcp <path>` CLI entry point is provided by the CLI engineer;
it calls `okfsmith.mcp_server.serve(bundle_path, transport="stdio")`.

## Python API

```python
from okfsmith.mcp_server import build_server, serve

server = build_server("./kb")          # bundle loaded once, server not started
serve("./kb")                          # stdio transport (default)
serve("./kb", transport="sse")         # or any FastMCP transport
```

Without the `mcp` extra installed, `build_server` / `serve` raise a
`RuntimeError` telling you to `pip install "okfsmith[mcp]"`.
