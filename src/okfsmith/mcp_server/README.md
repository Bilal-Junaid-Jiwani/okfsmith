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
| `index()` | Root `index.md` — the map of the whole knowledge base (start here); each entry carries the concept's temporal status, evaluated at the optional `as_of` replay instant when one is given, labeled in the output |
| `list(filter_type="", limit=50, tier_filter="")` | Concept inventory: id, type, trust tier, title; optional type filter and trust-tier filter (`unverified` / `machine-confirmed` / `human-reviewed`); a non-current concept carries its temporal status on its row (e.g. `_(superseded by `policy-v2`)_`) |
| `search(query, limit=10)` | Keyword search over id / title / description / tags / body, ranked by field; a non-current hit carries its temporal status on its row, evaluated at the `as_of` replay instant when one is given |
| `get(concept_id)` | Full concept: YAML frontmatter + markdown body; a non-current concept carries a note line under the document (e.g. `_Note: **policy-v1** is superseded by `policy-v2`._`), evaluated at the `as_of` replay instant when one is given |
| `neighbors(concept_id, as_of=None)` | Outgoing links + incoming backlinks, with the link text as the relation note; each row carries the linked concept's temporal status, evaluated at the optional `as_of` replay instant when one is given, labeled in the output |
| `traverse(concept_id, depth=1)` | Breadth-first walk of the link graph from one concept; superseded concepts hidden by default, current concepts sort first; optional `as_of` (ISO-8601 date/datetime) replays validity and supersession at that instant, labeled in the output |
| `provenance(concept_id)` | Trace a concept's sources, ingested-source records, and footnote references; the concept's temporal status line is evaluated at the optional `as_of` replay instant when one is given, labeled in the output |
| `diff(against=None, as_of=None)` | Diff against another bundle directory or the sync-state snapshot: added / removed / changed concepts with body SHA-256; each row carries the concept's temporal status, evaluated at the optional `as_of` replay instant when one is given, labeled in the output |
| `validate(strict=False, as_of=None)` | Validate the bundle against OKF v0.2 (E001–E004 / W001–W020) — the MCP analogue of `okfsmith validate`: conformance plus advisory warnings, with the verdict up top; optional `strict` treats warnings as failures, and optional `as_of` (ISO-8601 date/datetime) replays the clock-dependent warnings W006/W020 at that instant, labeled in the output |

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
