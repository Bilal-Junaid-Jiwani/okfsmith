# MCP server

`okfsmith mcp BUNDLE` serves a finished bundle to AI agents over the
Model Context Protocol. Requires the `mcp` extra:

```bash
pip install "okfsmith[mcp]"
```

## Transports

```bash
okfsmith mcp ./kb                          # stdio (default)
okfsmith mcp ./kb --transport sse          # server-sent events
okfsmith mcp ./kb --transport streamable-http
```

Anything else is a usage error (exit 2).

## Tools

| Tool | What it does |
|------|--------------|
| `index` | bundle overview: concept count, types, trust tiers |
| `list` | list concepts, optional type filter, paginated |
| `search` | full-text search over id / title / body |
| `get` | fetch one concept by id (frontmatter + body) |
| `neighbors` | 1-hop linked concepts (outlinks and backlinks) |
| `traverse` | breadth-first walk of the link graph from one concept |
| `provenance` | trace a concept's sources, ingested-source records, footnotes |
| `diff` | added / removed / changed concepts vs another bundle or snapshot |

## Governed write-back

Four tools let an agent add to the bundle under governance. Every write is
atomic (temp file + rename), always lands at the `unverified` trust tier,
stamps a `provenance` history entry in frontmatter (actor `mcp:<tool>`, UTC
timestamp, input sources), is gated on the bundle validator (new errors ⇒
refused and rolled back), never overwrites an existing concept, and is
recorded in the append-only `<bundle>/.okfsmith/audit.jsonl`.

| Tool | What it does |
|------|--------------|
| `preview_write_concept` | dry run: show exactly what `write_concept` would write, writing nothing |
| `write_concept` | create a concept; refuses on id collision (suggests `update_concept`) |
| `update_concept` | patch title / body / sources / links; refuses human-reviewed concepts without `downgrade_trust=true`; `dry_run=true` returns a diff |
| `audit_log` | recent write-back entries (timestamp, actor, action, concept id, summary) |

## Client configuration

Use **absolute** paths to the bundle. Replace `/home/you/kb` with your real
bundle directory.

### Claude Code / Claude Desktop (`~/.claude.json` or `claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "kb": {
      "command": "okfsmith",
      "args": ["mcp", "/home/you/kb"]
    }
  }
}
```

### Cursor (`~/.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "kb": {
      "command": "okfsmith",
      "args": ["mcp", "/home/you/kb"]
    }
  }
}
```

### VS Code with Copilot (`.vscode/mcp.json`)

```json
{
  "servers": {
    "kb": {
      "command": "okfsmith",
      "args": ["mcp", "/home/you/kb"]
    }
  }
}
```

### Gemini CLI (`~/.gemini/settings.json`)

```json
{
  "mcpServers": {
    "kb": {
      "command": "okfsmith",
      "args": ["mcp", "/home/you/kb"]
    }
  }
}
```

If `okfsmith` is installed via `pipx`, use the full path to the binary
(`~/.local/bin/okfsmith`) as `command`.
