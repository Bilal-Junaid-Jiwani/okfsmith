"""Tests for the dashboard launch layer: ``find_free_port`` / ``serve``
(``okfsmith.dashboard.server``) and the ``okfsmith dashboard`` CLI command
(``okfsmith.cli.dashboard_cmd``).

This layer previously had no test coverage at all, which let a real bug
ship: with port 65535 occupied, ``find_free_port(65535)`` incremented past
the top of the port range and crashed with a raw ``OverflowError``
traceback instead of a clean error. These tests pin the bounded scan,
the friendly CLI failure, and the loopback/token launch invariants.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from okfsmith.cli.app import app
from okfsmith.dashboard import server as dash_server
from okfsmith.dashboard.server import HOST, find_free_port

runner = CliRunner()


def _occupy(port: int) -> socket.socket:
    """Bind+listen on *port* (loopback) so port probes see it as taken.

    Skips the test when the OS refuses the bind outright (e.g. Windows
    excluded port ranges near the top of the range) — the probe behavior
    being tested is unobservable there either way.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((HOST, port))
    except OSError as exc:
        sock.close()
        pytest.skip(f"OS refuses to bind port {port}: {exc}")
    sock.listen(1)
    return sock


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return sock.getsockname()[1]


# ---------------------------------------------------------------------------
# find_free_port
# ---------------------------------------------------------------------------


def test_find_free_port_returns_preferred_when_free() -> None:
    port = _free_port()
    assert find_free_port(port) == port


def test_find_free_port_skips_occupied_port() -> None:
    port = _free_port()
    if port >= 65535:  # pragma: no cover - ephemeral range guard
        pytest.skip("no headroom above the ephemeral port")
    blocker = _occupy(port)
    try:
        assert find_free_port(port) == port + 1
    finally:
        blocker.close()


def test_find_free_port_exhausted_at_top_of_range() -> None:
    blocker = _occupy(65535)
    try:
        with pytest.raises(OSError, match="no free loopback port"):
            find_free_port(65535)
    finally:
        blocker.close()


def test_find_free_port_exhausted_range() -> None:
    blockers = [_occupy(65534), _occupy(65535)]
    try:
        with pytest.raises(OSError, match="65534-65535"):
            find_free_port(65534)
    finally:
        for blocker in blockers:
            blocker.close()


@pytest.mark.parametrize("bad", [0, -1, 65536, 70000])
def test_find_free_port_rejects_out_of_range(bad: int) -> None:
    with pytest.raises(ValueError, match="1-65535"):
        find_free_port(bad)


# ---------------------------------------------------------------------------
# serve (uvicorn + browser stubbed out; launch invariants only)
# ---------------------------------------------------------------------------


@pytest.fixture()
def _stub_uvicorn(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []

    def fake_run(app_, **kwargs) -> None:  # noqa: ANN001, ANN003
        calls.append({"app": app_, **kwargs})

    monkeypatch.setattr("uvicorn.run", fake_run)
    return calls


def test_serve_no_open_prints_token_url_and_binds_loopback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    _stub_uvicorn: list[dict],
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(dash_server.webbrowser, "open", opened.append)
    port = _free_port()
    dash_server.serve(tmp_path, port=port, no_open=True)
    out = capsys.readouterr().out
    assert f"http://{HOST}:{port}/" in out
    assert "?token=" in out  # operator needs the single-use URL
    assert opened == []  # --no-open must never open a browser
    assert len(_stub_uvicorn) == 1
    call = _stub_uvicorn[0]
    assert call["host"] == HOST
    assert call["port"] == port
    # The bootstrap URL carries the token; access logging must stay off.
    assert call["access_log"] is False


def test_serve_opens_browser_with_token_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _stub_uvicorn: list[dict],
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(dash_server.webbrowser, "open", opened.append)
    dash_server.serve(tmp_path, port=_free_port(), no_open=False)
    assert len(opened) == 1
    assert opened[0].startswith(f"http://{HOST}:")
    assert "?token=" in opened[0]


def test_serve_survives_browser_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    _stub_uvicorn: list[dict],
) -> None:
    def boom(_url: str) -> None:
        raise RuntimeError("no browser")

    monkeypatch.setattr(dash_server.webbrowser, "open", boom)
    dash_server.serve(tmp_path, port=_free_port(), no_open=False)
    out = capsys.readouterr().out
    assert "could not open browser" in out
    assert "?token=" in out  # manual URL printed as fallback
    assert len(_stub_uvicorn) == 1  # server still started


def test_serve_falls_back_when_preferred_port_taken(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    _stub_uvicorn: list[dict],
) -> None:
    port = _free_port()
    if port >= 65535:  # pragma: no cover - ephemeral range guard
        pytest.skip("no headroom above the ephemeral port")
    blocker = _occupy(port)
    try:
        dash_server.serve(tmp_path, port=port, no_open=True)
    finally:
        blocker.close()
    out = capsys.readouterr().out
    assert f"(port {port} was taken; using {port + 1})" in out
    assert _stub_uvicorn[0]["port"] == port + 1


# ---------------------------------------------------------------------------
# `okfsmith dashboard` CLI command
# ---------------------------------------------------------------------------


def test_dashboard_cmd_rejects_bad_port(tmp_path: Path) -> None:
    for bad in ("0", "65536"):
        result = runner.invoke(
            app, ["dashboard", "--port", bad, "--dir", str(tmp_path)]
        )
        assert result.exit_code == 2
        assert "bad-port" in result.output


def test_dashboard_cmd_rejects_missing_dir(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["dashboard", "--dir", str(tmp_path / "nope")]
    )
    assert result.exit_code == 2
    assert "bad-dir" in result.output


def test_dashboard_cmd_missing_deps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `None` in sys.modules makes `import fastapi` raise ImportError.
    monkeypatch.setitem(sys.modules, "fastapi", None)
    result = runner.invoke(app, ["dashboard", "--dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "dashboard-deps-missing" in result.output


def test_dashboard_cmd_delegates_to_serve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict = {}

    def fake_serve(workspace: Path, port: int, no_open: bool) -> None:
        seen.update(workspace=workspace, port=port, no_open=no_open)

    monkeypatch.setattr("okfsmith.dashboard.server.serve", fake_serve)
    result = runner.invoke(
        app,
        ["dashboard", "--port", "9999", "--no-open", "--dir", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    assert seen == {
        "workspace": tmp_path.resolve(),
        "port": 9999,
        "no_open": True,
    }


def test_dashboard_cmd_reports_start_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(workspace: Path, port: int, no_open: bool) -> None:
        raise OSError("no free loopback port in range 8931-65535")

    monkeypatch.setattr("okfsmith.dashboard.server.serve", fail)
    result = runner.invoke(app, ["dashboard", "--dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "dashboard-start-failed" in result.output
    assert "no free loopback port" in result.output
    assert result.exception is None or isinstance(
        result.exception, SystemExit
    )
