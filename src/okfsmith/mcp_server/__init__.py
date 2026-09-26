"""okfsmith MCP server — expose an OKF knowledge bundle to AI agents.

This package adapts :class:`okfsmith.core.bundle.Bundle` to the `Model Context
Protocol <https://modelcontextprotocol.io/>`_ via FastMCP. It is intentionally
**read-only**: the bundle is loaded once at startup and served for as many
tool calls as the client makes. There is no bundle mutation, no network
access, and no secrets handling.

FastMCP is an optional dependency — install it with::

    pip install "okfsmith[mcp]"

Use :func:`build_server` to construct the server (useful for tests), and
:func:`serve` as the CLI entry point (default stdio transport).
"""

from okfsmith.mcp_server.server import build_server, serve

__all__ = ["build_server", "serve"]
