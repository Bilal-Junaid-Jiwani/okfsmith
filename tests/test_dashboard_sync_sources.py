"""Status-contract tests for ``GET /api/v1/sync/sources``.

The endpoint is the dashboard's sync-health surface: it walks the real sync
state written by ``okfsmith sync`` and reports one record per source with
``{name, kind, status, last_sync, detail}`` where ``status`` is one of
``ok`` | ``stale`` | ``error``. Every branch below goes through the real
CLI (``init`` + ``ingest --no-llm`` + ``sync --no-llm``) and the real
``create_app``/TestClient pair — no hand-built sync state, no mocks.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from okfsmith.cli.app import app as cli_app
from okfsmith.core import Bundle
from okfsmith.core import sync as _sync_core
from okfsmith.dashboard.app import create_app

runner = CliRunner()
TEST_TOKEN = "okfsmith-test-token"

# Must stay above the sectioning stub threshold (default 1000 chars) or the
# sync produces no concepts and records nothing under "sources".
SOURCE_TEXT = (
    "# Sync Health Notes\n\n"
    + "The quick brown fox keeps this source in sync with the bundle. " * 40
    + "\n\n## Second Section\n\n"
    + "Pack my box with five dozen liquor jugs before the sync runs. " * 40
    + "\n"
)


# ----------------------------------------------------------------- fixtures --
@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """Workspace with a real bundle and a real synced source."""
    bundle_dir = tmp_path / "kb"
    assert runner.invoke(cli_app, ["init", str(bundle_dir)]).exit_code == 0
    source = tmp_path / "source.md"
    source.write_text(SOURCE_TEXT, encoding="utf-8")
    result = runner.invoke(
        cli_app, ["sync", str(bundle_dir), str(source), "--no-llm"]
    )
    assert result.exit_code == 0, result.output
    return tmp_path


@pytest.fixture()
def client(workspace: Path):
    """Fresh (TestClient, auth headers) pair per test."""
    app = create_app(workspace, TEST_TOKEN)
    return TestClient(app), {"Authorization": f"Bearer {TEST_TOKEN}"}


def _bundle_id(client: TestClient, headers: dict, name: str = "kb") -> str:
    bundles = client.get("/api/v1/bundles", headers=headers).json()["bundles"]
    matches = [b for b in bundles if b["name"] == name]
    assert matches, f"bundle {name!r} missing from {bundles}"
    return matches[0]["id"]


def _sources(client: TestClient, headers: dict) -> list[dict]:
    bid = _bundle_id(client, headers)
    payload = client.get(
        "/api/v1/sync/sources", params={"bundle_id": bid}, headers=headers
    ).json()
    assert set(payload) == {"sources"}
    return payload["sources"]


# -------------------------------------------------------------------- tests --
class TestSyncSourceStatuses:
    def test_ok_after_sync(self, client, workspace: Path):
        c, headers = client
        sources = _sources(c, headers)
        assert len(sources) == 1
        rec = sources[0]
        assert set(rec) == {"name", "kind", "status", "last_sync", "detail"}
        assert rec["name"] == "source.md"
        assert rec["kind"] == "markdown"
        assert rec["status"] == "ok"
        assert rec["last_sync"] is not None
        assert "in sync" in rec["detail"]

    def test_stale_after_source_edit(self, client, workspace: Path):
        c, headers = client
        assert _sources(c, headers)[0]["status"] == "ok"
        (workspace / "source.md").write_text(
            SOURCE_TEXT + "\nA brand-new paragraph nobody synced yet.\n",
            encoding="utf-8",
        )
        (rec,) = _sources(c, headers)
        assert rec["status"] == "stale"
        assert "changed since last sync" in rec["detail"]

    def test_error_after_source_delete(self, client, workspace: Path):
        c, headers = client
        (workspace / "source.md").unlink()
        (rec,) = _sources(c, headers)
        assert rec["status"] == "error"
        assert "no longer exists" in rec["detail"]

    def test_permanent_failure_is_error(self, client, workspace: Path):
        """A source the sync engine gave up on reports error with its reason."""
        c, headers = client
        bundle = Bundle.load(workspace / "kb")
        state = _sync_core.load_sync_state(bundle)
        src = str(workspace / "source.md")
        state["permanent_failures"][src] = {"error": "boom: parse failed"}
        path = _sync_core.sync_state_path(bundle)
        path.write_text(json.dumps(state), encoding="utf-8")

        (rec,) = _sources(c, headers)
        assert rec["status"] == "error"
        assert "boom: parse failed" in rec["detail"]

    def test_unknown_bundle_id_is_404(self, client):
        c, headers = client
        r = c.get(
            "/api/v1/sync/sources",
            params={"bundle_id": "no-such-bundle"},
            headers=headers,
        )
        assert r.status_code == 404
        payload = r.json()
        assert set(payload) == {"error", "message", "hint"}, payload
        assert payload["error"] == "bundle-not-found"


class TestDirectorySources:
    @pytest.fixture()
    def dir_workspace(self, tmp_path: Path) -> Path:
        bundle_dir = tmp_path / "kb"
        assert runner.invoke(cli_app, ["init", str(bundle_dir)]).exit_code == 0
        srcdir = tmp_path / "src"
        srcdir.mkdir()
        (srcdir / "note.md").write_text(SOURCE_TEXT, encoding="utf-8")
        result = runner.invoke(
            cli_app, ["sync", str(bundle_dir), str(srcdir), "--no-llm"]
        )
        assert result.exit_code == 0, result.output
        return tmp_path

    def test_directory_sync_records_each_file(self, dir_workspace: Path):
        """The sync engine expands a directory source into per-file records.

        So the endpoint reports the file *inside* the synced directory (not
        the directory itself), and a later edit of that file goes stale by
        the file-hash comparison, not the directory-mtime branch.
        """
        app = create_app(dir_workspace, TEST_TOKEN)
        c, headers = TestClient(app), {"Authorization": f"Bearer {TEST_TOKEN}"}
        bid = _bundle_id(c, headers)
        payload = c.get(
            "/api/v1/sync/sources", params={"bundle_id": bid}, headers=headers
        ).json()
        assert len(payload["sources"]) == 1
        (rec,) = payload["sources"]
        assert rec["name"] == "note.md"
        assert rec["kind"] == "markdown"
        assert rec["status"] == "ok"

        (dir_workspace / "src" / "note.md").write_text(
            SOURCE_TEXT + "\nA late addition inside the synced directory.\n",
            encoding="utf-8",
        )
        (rec,) = c.get(
            "/api/v1/sync/sources", params={"bundle_id": bid}, headers=headers
        ).json()["sources"]
        assert rec["status"] == "stale"
        assert "changed since last sync" in rec["detail"]
