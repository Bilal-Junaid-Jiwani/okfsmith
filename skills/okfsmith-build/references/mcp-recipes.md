# MCP Recipes — attach an OKF bundle to your agent

`okfsmith mcp --bundle ./kb` starts a FastMCP server over stdio exposing five
tools against the bundle: `search`, `get`, `list`, `neighbors`, `index`.
Point any MCP-capable agent at the stdio server and every answer traces back
to the bundle's `sources[]` provenance.

The bundle path must be absolute (or resolvable from the client's working
directory). Replace `/abs/path/to/kb` below.

## Claude Code

```bash
claude mcp add okfsmith -- uvx okfsmith mcp --bundle /abs/path/to/kb
```

Or declare it in `.mcp.json` at the project root:

```json
{
  "mcpServers": {
    "okfsmith": {
      "command": "uvx",
      "args": ["okfsmith", "mcp", "--bundle", "/abs/path/to/kb"]
    }
  }
}
```

## Cursor

`.cursor/mcp.json` in the project root:

```json
{
  "mcpServers": {
    "okfsmith": {
      "command": "uvx",
      "args": ["okfsmith", "mcp", "--bundle", "/abs/path/to/kb"]
    }
  }
}
```

Restart Cursor (or toggle the server in Settings → MCP) to pick it up.

## VS Code / Muse

Workspace `.vscode/mcp.json`:

```json
{
  "servers": {
    "okfsmith": {
      "type": "stdio",
      "command": "uvx",
      "args": ["okfsmith", "mcp", "--bundle", "/abs/path/to/kb"]
    }
  }
}
```

Enable the server from the MCP view; Copilot's agent mode can then call
`search`/`get`/`list`/`neighbors`/`index` as tools.

## Gemini CLI

`.gemini/settings.json` (project root or `~/.gemini/settings.json`):

```json
{
  "mcpServers": {
    "okfsmith": {
      "command": "uvx",
      "args": ["okfsmith", "mcp", "--bundle", "/abs/path/to/kb"]
    }
  }
}
```

## Troubleshooting

- `uvx` not found → install `uv`, or replace `command` with the path to a
  Python that has okfsmith installed and `args` with
  `["-m", "okfsmith", "mcp", "--bundle", "/abs/path/to/kb"]`.
- The server reads the bundle from disk on each call, so re-running
  `okfsmith ingest` needs no server restart.
- stdio servers are per-client: each of the configs above launches its own
  `okfsmith mcp` process; they do not conflict.
