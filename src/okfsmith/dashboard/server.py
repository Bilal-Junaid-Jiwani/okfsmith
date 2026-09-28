"""Launch helpers for the dashboard server.

Finds a free loopback port, mints the per-launch token, optionally opens the
browser with the one-time ``?token=``, and runs uvicorn bound to 127.0.0.1
only. The token value is never logged.
"""

from __future__ import annotations

import socket
import webbrowser
from pathlib import Path

DEFAULT_PORT = 8931
HOST = "127.0.0.1"


def find_free_port(preferred: int = DEFAULT_PORT) -> int:
    """Return *preferred* if free on loopback, else the next free port."""
    port = preferred
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((HOST, port))
            except OSError:
                port += 1
                continue
            return port


def serve(workspace: Path, port: int = DEFAULT_PORT, no_open: bool = False) -> None:
    """Start the dashboard server (blocking)."""
    import uvicorn

    from okfsmith.dashboard.app import create_app
    from okfsmith.dashboard.auth import new_token

    token = new_token()
    actual_port = find_free_port(port)
    app = create_app(workspace, token)
    base = f"http://{HOST}:{actual_port}/"
    print(f"okfsmith dashboard: {base}")
    if actual_port != port:
        print(f"(port {port} was taken; using {actual_port})")
    if no_open:
        # The operator needs the single-use token URL to get in at all.
        print(f"single-use token URL: {base}?token={token}")
    else:
        try:
            webbrowser.open(f"{base}?token={token}")
        except Exception as exc:  # never fail launch on browser errors
            print(f"could not open browser: {exc}")
            print("open this single-use URL manually:")
            print(f"{base}?token={token}")
    # Access logging stays off: the browser bootstrap URL carries ?token=...,
    # which must never land in a log file.
    uvicorn.run(app, host=HOST, port=actual_port, log_level="info", access_log=False)
