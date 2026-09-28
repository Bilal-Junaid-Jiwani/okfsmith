"""okfsmith local web dashboard.

A single-user, loopback-only FastAPI server exposing every okfsmith CLI
feature as a JSON API for the vanilla SPA in ``static/``. All business
logic is reused from the existing slices (``core``, ``parsers``,
``extract``, ``validate``, ``search``, ``viz``, ``eval``, ``mcp_server``,
``cli``) — this package only wires HTTP to those entry points.
"""

from __future__ import annotations

__all__ = ["__version__"]

try:
    from okfsmith import __version__
except Exception:  # pragma: no cover - package metadata missing
    __version__ = "0.0.0"
