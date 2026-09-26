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
