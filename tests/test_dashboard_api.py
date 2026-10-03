"""API tests for the okfsmith web dashboard (``src/okfsmith/dashboard/``).

Exercises the dashboard HTTP surface through FastAPI's TestClient against
the real app factory ``create_app(workspace, token)`` with real backend
logic throughout:

- Auth: /health needs no token; every other /api/* route 401s without one;
  a Bearer header works; a ``?token=`` is single-use and burns after first use.
- Bundles: a tiny real bundle is built with the actual ``okfsmith init`` +
  ``okfsmith ingest`` CLI commands on a small markdown file, and the bundle /
  concept / graph / search / snapshot endpoints are asserted against that
  real data (no mocks, no hand-built concept JSON).
- Ingest: a multipart upload with ``dry_run`` as the string ``"true"``
  returns a dry_run_report and writes nothing.
- Validate: a background run returns per-rule results in the contract shape.
- Eval: 422 ``no_golden_set`` without a golden set; a real run (sample golden
  set written by the real ``okfsmith eval --init-sample``) returns a triad
  and CI gate.
- Doctor, chat (extractive), settings (write-only secrets), MCP governed
  write-back (preview -> write -> audit log entry), activity, SSE events,
  and the served SPA index.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from okfsmith import __version__
from okfsmith.cli.app import app as cli_app
from okfsmith.core import Bundle
from okfsmith.dashboard.app import create_app

runner = CliRunner()
TEST_TOKEN = "qa-test-token-0123456789abcdef"

# Source markdown for the fixture bundle. Must stay above the
# sectioning.TOO_SMALL_CHARS (1000) minimum or ingest skips it as a stub.
SOURCE_TEXT = (
    "# Dashboard QA Notes\n\n"
    + "The quick brown fox jumps over the lazy dog near the dashboard. " * 40
    + "\n\n## Packing Section\n\n"
    + "Pack my box with five dozen liquor jugs before the release. " * 40
    + "\n"
)


# ---------------------------------------------------------------- fixtures --
@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """Workspace holding one real bundle built via the real CLI commands."""
    bundle_dir = tmp_path / "kb"
    result = runner.invoke(cli_app, ["init", str(bundle_dir)])
    assert result.exit_code == 0, result.output
    source = tmp_path / "source.md"
    source.write_text(SOURCE_TEXT, encoding="utf-8")
    result = runner.invoke(cli_app, ["ingest", str(bundle_dir), str(source), "--no-llm"])
    assert result.exit_code == 0, result.output
    assert "ingested 2 concept(s)" in result.output
    return tmp_path


@pytest.fixture()
def client(workspace: Path):
    """Fresh (TestClient, auth headers) pair per test — fresh token state."""
    app = create_app(workspace, TEST_TOKEN)
    return TestClient(app), {"Authorization": f"Bearer {TEST_TOKEN}"}


def _bundle_id(client: TestClient, headers: dict, name: str = "kb") -> str:
    bundles = client.get("/api/v1/bundles", headers=headers).json()["bundles"]
    matches = [b for b in bundles if b["name"] == name]
    assert matches, f"bundle {name!r} missing from {bundles}"
    return matches[0]["id"]


def _wait_for(get_json, timeout: float = 60.0) -> dict:
    """Poll a background run/job until it leaves queued/running."""
    deadline = time.time() + timeout
    while True:
        payload = get_json()
        assert payload["status"] in ("queued", "running", "done", "error"), payload
        if payload["status"] in ("done", "error"):
            return payload
        assert time.time() < deadline, f"timed out waiting for {payload}"
        time.sleep(0.2)


def _error_shape(payload: dict) -> None:
    assert set(payload) == {"error", "message", "hint"}, payload


# -------------------------------------------------------------------- auth --
class TestAuth:
    def test_health_needs_no_token(self, client):
        c, _ = client
        r = c.get("/api/v1/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok", "version": __version__}

    def test_api_requires_token(self, client):
        c, _ = client
        r = c.get("/api/v1/bundles")
        assert r.status_code == 401
        _error_shape(r.json())
        assert r.json()["error"] == "unauthorized"

    def test_wrong_token_rejected(self, client):
        c, _ = client
        r = c.get("/api/v1/bundles", headers={"Authorization": "Bearer nope"})
        assert r.status_code == 401
        _error_shape(r.json())

    def test_bearer_token_works(self, client):
        c, headers = client
        r = c.get("/api/v1/bundles", headers=headers)
        assert r.status_code == 200
        assert "bundles" in r.json()

    def test_single_use_query_token_burns(self, workspace):
        # Dedicated app: the single-use query token must not disturb the
        # Bearer-token fixture used by every other test.
        c = TestClient(create_app(workspace, TEST_TOKEN))
        first = c.get(f"/api/v1/bundles?token={TEST_TOKEN}")
        assert first.status_code == 200
        second = c.get(f"/api/v1/bundles?token={TEST_TOKEN}")
        assert second.status_code == 401
        _error_shape(second.json())


# ------------------------------------------------------------------ bundles --
class TestBundles:
    def test_list_shape_and_real_counts(self, client):
        c, headers = client
        bundles = c.get("/api/v1/bundles", headers=headers).json()["bundles"]
        kb = next(b for b in bundles if b["name"] == "kb")
        assert set(kb) == {
            "id", "name", "path", "concepts", "sources",
            "trust_tiers", "updated_at", "size_bytes",
        }
        assert kb["concepts"] == 2  # the real ingest created exactly two
        assert kb["sources"] >= 1
        assert set(kb["trust_tiers"]) == {"high", "medium", "low"}
        assert sum(kb["trust_tiers"].values()) == 2
        assert kb["size_bytes"] > 0
        assert kb["updated_at"] is not None

    def test_concepts_list_real_data(self, client):
        c, headers = client
        bid = _bundle_id(c, headers)
        payload = c.get(f"/api/v1/bundles/{bid}/concepts", headers=headers).json()
        assert payload["total"] == 2
        assert payload["page"] == 1
        ids = {item["id"] for item in payload["items"]}
        assert ids == {"source/dashboard-qa-notes", "source/packing-section"}
        for item in payload["items"]:
            assert set(item) == {"id", "title", "tier", "sources", "updated_at"}
            assert item["tier"] in ("high", "medium", "low")

    def test_concepts_query_filter(self, client):
        c, headers = client
        bid = _bundle_id(c, headers)
        payload = c.get(
            f"/api/v1/bundles/{bid}/concepts", params={"q": "packing"},
            headers=headers,
        ).json()
        assert payload["total"] == 1
        assert payload["items"][0]["id"] == "source/packing-section"

    def test_concept_detail_real_data(self, client):
        c, headers = client
        bid = _bundle_id(c, headers)
        detail = c.get(
            f"/api/v1/bundles/{bid}/concepts/source/dashboard-qa-notes",
            headers=headers,
        ).json()
        assert set(detail) == {
            "id", "title", "tier", "frontmatter", "body",
            "sources", "provenance",
        }
        assert detail["title"] == "Dashboard QA Notes"
        # Real ingested body text, not fixture JSON.
        assert "The quick brown fox jumps over the lazy dog" in detail["body"]
        assert detail["sources"], "ingested concepts carry their source file"

    def test_concept_404_shape(self, client):
        c, headers = client
        bid = _bundle_id(c, headers)
        r = c.get(f"/api/v1/bundles/{bid}/concepts/no-such-concept", headers=headers)
        assert r.status_code == 404
        _error_shape(r.json())

    def test_graph_shape(self, client):
        c, headers = client
        bid = _bundle_id(c, headers)
        graph = c.get(f"/api/v1/bundles/{bid}/graph", headers=headers).json()
        assert set(graph) == {"nodes", "edges", "truncated"}
        node_ids = {n["id"] for n in graph["nodes"]}
        assert node_ids == {"source/dashboard-qa-notes", "source/packing-section"}
        for node in graph["nodes"]:
            assert set(node) == {"id", "label", "tier"}
        assert graph["truncated"] is False

    def test_search_real_hits(self, client):
        c, headers = client
        bid = _bundle_id(c, headers)
        results = c.get(
            "/api/v1/search", params={"q": "liquor jugs", "bundle_id": bid},
            headers=headers,
        ).json()["results"]
        assert results, "real ingest must be searchable"
        hit = results[0]
        assert set(hit) == {"bundle_id", "concept_id", "title", "snippet", "score"}
        assert hit["concept_id"] == "source/packing-section"
        assert isinstance(hit["score"], float)
        assert "liquor jugs" in hit["snippet"]

    def test_snapshot(self, client):
        c, headers = client
        bid = _bundle_id(c, headers)
        payload = c.get(
            f"/api/v1/bundles/{bid}/snapshot",
            params={"as_of": "2026-09-28T00:00:00+00:00"},
            headers=headers,
        ).json()
        assert payload["as_of"].startswith("2026-09-28")
        assert len(payload["concepts"]) == 2
        for concept in payload["concepts"]:
            assert set(concept) >= {"id", "title", "tier", "valid_from", "valid_to"}

    def test_snapshot_bad_datetime(self, client):
        c, headers = client
        bid = _bundle_id(c, headers)
        r = c.get(
            f"/api/v1/bundles/{bid}/snapshot", params={"as_of": "not-a-date"},
            headers=headers,
        )
        assert r.status_code == 400
        _error_shape(r.json())


# ------------------------------------------------------------------- ingest --
class TestIngest:
    # Deliberately DIFFERENT bytes from the fixture source: identical bytes
    # would hit the real SHA-256 dedup ("would skip (already ingested)").
    DRY_RUN_TEXT = (
        "# Dry Run Planning Doc\n\n"
        + "Sphinx of black quartz judge my vow without delay. " * 40
        + "\n\n## Second Dry Section\n\n"
        + "How vexingly quick daft zebras jump across the field. " * 40
        + "\n"
    )

    def _post_dry_run(self, c, headers, bid):
        return c.post(
            "/api/v1/ingest",
            files=[("files[]", ("dry.md", self.DRY_RUN_TEXT.encode(), "text/markdown"))],
            data={"bundle_id": bid, "dry_run": "true", "source_kind": "markdown"},
            headers=headers,
        )

    def test_dry_run_reports_and_writes_nothing(self, client, workspace):
        c, headers = client
        bid = _bundle_id(c, headers)
        before = len(list(Bundle.load(workspace / "kb").iter_concepts()))
        r = self._post_dry_run(c, headers, bid)
        assert r.status_code == 202
        job = _wait_for(
            lambda: c.get(f"/api/v1/ingest/jobs/{r.json()['job_id']}", headers=headers).json()
        )
        assert job["status"] == "done"
        assert job["dry_run"] is True
        report = job["dry_run_report"]
        assert report["would_create"] == 2
        assert report["notes"], "dry run must explain what would happen"
        after = len(list(Bundle.load(workspace / "kb").iter_concepts()))
        assert after == before == 2, "dry_run must not write concepts"

    def test_dry_run_steps_are_real(self, client):
        c, headers = client
        bid = _bundle_id(c, headers)
        r = self._post_dry_run(c, headers, bid)
        job = _wait_for(
            lambda: c.get(f"/api/v1/ingest/jobs/{r.json()['job_id']}", headers=headers).json()
        )
        step_names = [s["name"] for s in job["steps"]]
        assert step_names == ["parse", "chunk", "embed", "validate", "index"]
        for step in job["steps"]:
            assert step["state"] == "done", step

    def test_ingest_requires_files(self, client):
        c, headers = client
        bid = _bundle_id(c, headers)
        r = c.post("/api/v1/ingest", data={"bundle_id": bid}, headers=headers)
        assert r.status_code == 400
        _error_shape(r.json())

    def test_ingest_events_sse(self, client):
        c, headers = client
        bid = _bundle_id(c, headers)
        r = self._post_dry_run(c, headers, bid)
        job_id = r.json()["job_id"]
        frames: list[dict] = []
        with c.stream(
            "GET", f"/api/v1/ingest/jobs/{job_id}/events", headers=headers
        ) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    frames.append(json.loads(line[len("data: "):]))
                if frames and frames[-1].get("status") in ("done", "error"):
                    break
                if len(frames) > 40:
                    break
        assert frames, "SSE must emit at least one event frame"
        assert all({"step", "state"} <= set(f) or "status" in f for f in frames)
        states = {f["state"] for f in frames if "step" in f}
        assert "done" in states


# --------------------------------------------------------------------- sync --
class TestSync:
    def test_sync_sources_shape(self, client):
        c, headers = client
        bid = _bundle_id(c, headers)
        payload = c.get(
            "/api/v1/sync/sources", params={"bundle_id": bid}, headers=headers
        ).json()
        assert set(payload) == {"sources"}
        # The fixture bundle has no synced sources yet: honest empty list.
        assert payload["sources"] == []

    def test_sync_run_without_sources_is_422(self, client):
        c, headers = client
        bid = _bundle_id(c, headers)
        r = c.post("/api/v1/sync/runs", json={"bundle_id": bid}, headers=headers)
        assert r.status_code == 422
        _error_shape(r.json())


# ----------------------------------------------------------------- validate --
class TestValidate:
    def test_run_returns_per_rule_results(self, client):
        c, headers = client
        bid = _bundle_id(c, headers)
        r = c.post("/api/v1/validate/runs", json={"bundle_id": bid}, headers=headers)
        assert r.status_code == 202
        run = _wait_for(
            lambda: c.get(f"/api/v1/validate/runs/{r.json()['run_id']}", headers=headers).json()
        )
        assert run["status"] == "done"
        summary = run["summary"]
        assert set(summary) == {"pass", "fail", "warn"}  # contract shape
        assert all(isinstance(v, int) for v in summary.values())
        assert len(run["rules"]) > 0
        for rule in run["rules"]:
            assert set(rule) == {"rule", "status", "message", "concepts"}  # contract
            assert rule["status"] in ("pass", "fail", "warn")
            assert isinstance(rule["message"], str)
            assert isinstance(rule["concepts"], list)

    def test_summary_counts_are_consistent(self, client):
        c, headers = client
        bid = _bundle_id(c, headers)
        r = c.post("/api/v1/validate/runs", json={"bundle_id": bid}, headers=headers)
        run = _wait_for(
            lambda: c.get(f"/api/v1/validate/runs/{r.json()['run_id']}", headers=headers).json()
        )
        summary = run["summary"]
        tallied = {"pass": 0, "fail": 0, "warn": 0}
        for rule in run["rules"]:
            tallied[rule["status"]] += 1
        assert summary == tallied


# --------------------------------------------------------------------- eval --
class TestEval:
    def test_no_golden_set_is_422(self, client):
        c, headers = client
        bid = _bundle_id(c, headers)
        r = c.post("/api/v1/eval/runs", json={"bundle_id": bid}, headers=headers)
        assert r.status_code == 422
        payload = r.json()
        assert payload["error"] == "no_golden_set"
        assert payload["hint"], "honest empty state needs a hint"

    def test_run_with_golden_set(self, client, workspace):
        c, headers = client
        bid = _bundle_id(c, headers)
        # Real golden set via the real CLI sample writer.
        result = runner.invoke(cli_app, ["eval", str(workspace / "kb"), "--init-sample"])
        assert result.exit_code == 0, result.output
        r = c.post("/api/v1/eval/runs", json={"bundle_id": bid}, headers=headers)
        assert r.status_code == 202
        run = _wait_for(
            lambda: c.get(f"/api/v1/eval/runs/{r.json()['run_id']}", headers=headers).json(),
            timeout=120.0,
        )
        assert run["status"] == "done"
        triad = run["triad"]
        assert set(triad) == {"context", "groundedness", "answer_relevance"}
        assert all(isinstance(v, (int, float)) for v in triad.values())
        assert run["ci_gate"]["status"] in ("pass", "fail")
        assert run["questions"], "questions must come from the real golden set"
        runs = c.get("/api/v1/eval/runs", headers=headers).json()["runs"]
        assert any(entry["run_id"] == run["run_id"] for entry in runs)


# ------------------------------------------------------------------- doctor --
class TestDoctor:
    def test_doctor_shape(self, client):
        c, headers = client
        checks = c.get("/api/v1/doctor", headers=headers).json()["checks"]
        assert len(checks) > 0
        for check in checks:
            assert set(check) == {"name", "status", "detail"}
            assert check["status"] in ("pass", "warn", "fail")
            assert isinstance(check["detail"], str)


# --------------------------------------------------------------------- chat --
class TestChat:
    def test_providers_shape(self, client):
        c, headers = client
        providers = c.get("/api/v1/chat/providers", headers=headers).json()["providers"]
        assert len(providers) == 16  # all presets, per contract
        for provider in providers:
            assert set(provider) == {"id", "name", "description"}
        by_id = {p["id"]: p for p in providers}
        # Anthropic is the one non-OpenAI-compatible preset: the dashboard
        # must label its wire format honestly.
        assert "Native Anthropic Messages API" in by_id["anthropic"]["description"]
        for pid, p in by_id.items():
            if pid != "anthropic":
                assert "OpenAI-compatible" in p["description"]
        blob = json.dumps(providers).lower()
        assert "api_key" not in blob and "secret" not in blob

    def test_extractive_message_grounded(self, client):
        c, headers = client
        bid = _bundle_id(c, headers)
        sid = c.post(
            "/api/v1/chat/sessions", json={"bundle_id": bid}, headers=headers
        ).json()["session_id"]
        try:
            payload = c.post(
                f"/api/v1/chat/sessions/{sid}/messages",
                json={"message": "What does the dashboard QA document say?"},
                headers=headers,
            ).json()
            assert isinstance(payload["answer"], str) and payload["answer"].strip()
            assert "\x1b" not in payload["answer"], "answer must be ANSI-free"
            assert payload["citations"], "grounded answer must cite real concepts"
            cited = {cite["concept_id"] for cite in payload["citations"]}
            assert cited <= {"source/dashboard-qa-notes", "source/packing-section"}
        finally:
            r = c.delete(f"/api/v1/chat/sessions/{sid}", headers=headers)
            assert r.json() == {"ok": True}


# ---------------------------------------------------------------------- mcp --
class TestMcp:
    def test_status_and_tool_catalog(self, client):
        c, headers = client
        status = c.get("/api/v1/mcp/status", headers=headers).json()
        assert status["available"] is True
        for tool in ("traverse", "provenance", "diff"):
            assert tool in status["tools"]
        tools = c.get("/api/v1/mcp/tools", headers=headers).json()["tools"]
        names = {t["name"] for t in tools}
        assert {"traverse", "provenance", "diff", "preview_write_concept",
                "write_concept", "update_concept", "audit_log"} <= names
        for tool in tools:
            assert set(tool) == {"name", "description", "params"}

    def test_write_requires_approval(self, client):
        c, headers = client
        bid = _bundle_id(c, headers)
        preview = c.post(
            "/api/v1/mcp/preview_write",
            json={"bundle_id": bid, "operation": "create",
                  "payload": {"title": "MCP QA Concept",
                              "body": "A concept written through the dashboard MCP write-back path."}},
            headers=headers,
        ).json()
        r = c.post(
            "/api/v1/mcp/write",
            json={"preview_id": preview["preview_id"], "approved": False},
            headers=headers,
        )
        assert r.status_code == 422
        assert r.json()["error"] == "not-approved"

    def test_preview_write_audit_log(self, client):
        c, headers = client
        bid = _bundle_id(c, headers)
        preview = c.post(
            "/api/v1/mcp/preview_write",
            json={"bundle_id": bid, "operation": "create",
                  "payload": {"title": "MCP QA Concept",
                              "body": "A concept written through the dashboard MCP write-back path."}},
            headers=headers,
        ).json()
        assert set(preview) == {"preview_id", "summary", "diff", "warnings"}
        r = c.post(
            "/api/v1/mcp/write",
            json={"preview_id": preview["preview_id"], "approved": True},
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["audit_id"]
        entries = c.get(
            "/api/v1/mcp/audit_log", params={"bundle_id": bid}, headers=headers
        ).json()["entries"]
        assert entries, "the write must append an audit entry"
        entry = entries[0]
        assert set(entry) == {"ts", "actor", "action", "concept_id", "detail"}
        assert entry["action"] == "create"
        assert entry["concept_id"] == "mcp-qa-concept"
        # The concept really exists in the bundle now.
        concepts = c.get(f"/api/v1/bundles/{bid}/concepts", headers=headers).json()
        assert "mcp-qa-concept" in {i["id"] for i in concepts["items"]}

    def test_write_unknown_preview_404(self, client):
        c, headers = client
        r = c.post(
            "/api/v1/mcp/write",
            json={"preview_id": "preview-does-not-exist", "approved": True},
            headers=headers,
        )
        assert r.status_code == 404
        _error_shape(r.json())


# ----------------------------------------------------------------- settings --
class TestSettings:
    def test_secrets_are_write_only(self, client):
        c, headers = client
        secret_value = "sk-qa-secret-never-echoed-12345"
        saved = dict(os.environ)
        try:
            r = c.put(
                "/api/v1/settings",
                json={"config": {}, "secrets": {"OKFSMITH_API_KEY": secret_value}},
                headers=headers,
            )
            assert r.status_code == 200
            assert r.json() == {"ok": True}
            assert secret_value not in json.dumps(r.json())
            settings = c.get("/api/v1/settings", headers=headers).json()
            assert "OKFSMITH_API_KEY" in settings["secrets_set"]
            assert secret_value not in json.dumps(settings), "secret must never be echoed"
        finally:
            os.environ.clear()
            os.environ.update(saved)

    def test_put_config_round_trip(self, client):
        c, headers = client
        saved = dict(os.environ)
        try:
            os.environ.pop("OKFSMITH_PROVIDER", None)
            r = c.put(
                "/api/v1/settings",
                json={"config": {"provider": "groq"}, "secrets": {}},
                headers=headers,
            )
            assert r.json() == {"ok": True}
            settings = c.get("/api/v1/settings", headers=headers).json()
            assert settings["config"]["provider"] == "groq"
            assert any(
                p["id"] == "groq" and p["is_default"] for p in settings["providers"]
            )
        finally:
            os.environ.clear()
            os.environ.update(saved)

    def test_unknown_secret_key_rejected(self, client):
        c, headers = client
        r = c.put(
            "/api/v1/settings",
            json={"config": {}, "secrets": {"EVIL_KEY": "x"}},
            headers=headers,
        )
        assert r.status_code == 400
        _error_shape(r.json())


# ----------------------------------------------------------------- activity --
class TestActivity:
    def test_activity_shape(self, client):
        c, headers = client
        items = c.get("/api/v1/activity", headers=headers).json()["items"]
        assert isinstance(items, list)
        assert items, "init + ingest wrote real log entries"
        for item in items[:5]:
            assert set(item) == {"ts", "date_only", "kind", "message"}
            # log.md entries are date-only: the timestamp must be midnight
            # and honestly flagged so the UI never invents a relative time.
            assert item["date_only"] is True
            assert item["ts"].endswith("T00:00:00+00:00")


# ---------------------------------------------------------------------- spa --
class TestSpa:
    def test_index_served(self, client):
        c, _ = client
        r = c.get("/")
        assert r.status_code == 200
        assert "okfsmith" in r.text.lower()

    def test_static_asset_served(self, client):
        c, _ = client
        r = c.get("/styles.css")
        assert r.status_code == 200
        assert "text/css" in r.headers["content-type"]


# ------------------------------------------------------- polish regressions --
class TestPolishRegressions:
    """Regression tests for the 2026-09-28 design/functional audit fixes."""

    def test_bundles_list_excludes_non_bundles(self, client, workspace, tmp_path):
        # A docs-style dir (index.md without okf_version), a hidden dir, and
        # a plain nested-md dir must never appear as bundles.
        c, headers = client
        docs = workspace / "docs"
        docs.mkdir()
        (docs / "index.md").write_text("# docs site index\n\nJust documentation.\n", encoding="utf-8")
        hidden = workspace / ".cache"
        hidden.mkdir()
        (hidden / "notes.md").write_text("# hidden notes\n", encoding="utf-8")
        bundles = c.get("/api/v1/bundles", headers=headers).json()["bundles"]
        names = [b["name"] for b in bundles]
        assert names == ["kb"], f"phantom bundles leaked in: {names}"

    def test_bundles_no_ancestor_double_count(self, client, workspace):
        # The workspace root "looking like a bundle" only because it contains
        # a real bundle must not double every concept count.
        c, headers = client
        # The fixture's ingest source scaffolding must not count as the
        # root's own bundle content (each test gets a fresh fixture dir).
        (workspace / "source.md").unlink()
        (workspace / "index.md").write_text(
            "---\nokf_version: '0.2'\n---\n\n# Index\n", encoding="utf-8"
        )
        bundles = c.get("/api/v1/bundles", headers=headers).json()["bundles"]
        names = [b["name"] for b in bundles]
        assert names == ["kb"], f"ancestor double-count: {names}"
        total = sum(b["concepts"] for b in bundles)
        concepts = c.get(
            f"/api/v1/bundles/{_bundle_id(c, headers)}/concepts", headers=headers
        ).json()["total"]
        assert total == concepts == 2

    def test_eval_triad_answer_relevancy_mapped(self, client, workspace):
        # The engine's canonical key is "answer_relevancy"; the dashboard
        # contract exposes it as "answer_relevance" — it must not read 0.0
        # forever because of a key mismatch.
        c, headers = client
        bid = _bundle_id(c, headers)
        result = runner.invoke(cli_app, ["eval", str(workspace / "kb"), "--init-sample"])
        assert result.exit_code == 0, result.output
        r = c.post("/api/v1/eval/runs", json={"bundle_id": bid}, headers=headers)
        assert r.status_code == 202
        run = _wait_for(
            lambda: c.get(f"/api/v1/eval/runs/{r.json()['run_id']}", headers=headers).json(),
            timeout=120.0,
        )
        assert run["status"] == "done"
        assert run["triad"]["answer_relevance"] == 1.0
        for q in run["questions"]:
            assert q["answer_relevance"] == 1.0

    def test_ingest_rejects_unsupported_file_type(self, client, workspace):
        c, headers = client
        before = {b["name"] for b in c.get("/api/v1/bundles", headers=headers).json()["bundles"]}
        r = c.post(
            "/api/v1/ingest",
            headers=headers,
            files={"files[]": ("evil.exe", b"MZ fake binary", "application/octet-stream")},
            data={"new_bundle": "junk-should-not-exist", "source_kind": "auto"},
        )
        assert r.status_code == 400
        _error_shape(r.json())
        assert not (workspace / "junk-should-not-exist").exists()
        after = {b["name"] for b in c.get("/api/v1/bundles", headers=headers).json()["bundles"]}
        assert after == before

    def test_ingest_empty_upload_leaves_no_junk_bundle(self, client, workspace):
        # A zero-byte upload is a 400 before any bundle directory exists.
        c, headers = client
        r = c.post(
            "/api/v1/ingest",
            headers=headers,
            files={"files[]": ("nothing.txt", b"", "text/plain")},
            data={"new_bundle": "empty-junk"},
        )
        assert r.status_code == 400
        _error_shape(r.json())
        assert not (workspace / "empty-junk").exists(), "junk bundle left behind"
        names = [b["name"] for b in c.get("/api/v1/bundles", headers=headers).json()["bundles"]]
        assert "empty-junk" not in names

    def test_ingest_zero_concept_upload_removes_new_bundle(self, client, workspace):
        # A file too small to section (stub prevention) yields zero concepts;
        # the just-created bundle dir must be removed again.
        c, headers = client
        r = c.post(
            "/api/v1/ingest",
            headers=headers,
            files={"files[]": ("tiny.txt", b"too small", "text/plain")},
            data={"new_bundle": "tiny-junk"},
        )
        assert r.status_code == 202
        job = _wait_for(
            lambda: c.get(f"/api/v1/ingest/jobs/{r.json()['job_id']}", headers=headers).json(),
            timeout=60.0,
        )
        assert job["status"] == "done"
        assert not (workspace / "tiny-junk").exists(), "junk bundle left behind"
        names = [b["name"] for b in c.get("/api/v1/bundles", headers=headers).json()["bundles"]]
        assert "tiny-junk" not in names

    def test_ingest_provenance_uses_original_filename(self, client, workspace):
        # Concept "resource" provenance must be the original upload filename,
        # never the deleted /tmp staging path.
        c, headers = client
        bid = _bundle_id(c, headers)
        before_ids = {item["id"] for item in c.get(
            f"/api/v1/bundles/{bid}/concepts", headers=headers).json()["items"]}
        r = c.post(
            "/api/v1/ingest",
            headers=headers,
            files={"files[]": ("product-handbook.md",
                               (SOURCE_TEXT + "\n\n## Handbook Addendum\n\n" +
                                "How vexingly quick daft zebras jump near the handbook. " * 40).encode(),
                               "text/markdown")},
            data={"bundle_id": bid},
        )
        assert r.status_code == 202
        job = _wait_for(
            lambda: c.get(f"/api/v1/ingest/jobs/{r.json()['job_id']}", headers=headers).json(),
            timeout=60.0,
        )
        assert job["status"] == "done", job
        items = c.get(f"/api/v1/bundles/{bid}/concepts", headers=headers).json()["items"]
        new_items = [i for i in items if i["id"] not in before_ids]
        assert new_items, "expected new concepts from the dashboard ingest"
        resources = [s for item in new_items for s in (item.get("sources") or [])]
        assert resources, "expected ingested concepts to carry sources"
        assert all("/tmp/" not in s and "okfsmith-ingest-" not in s for s in resources), resources
        assert any("product-handbook" in s for s in resources), resources

    def test_ingest_duplicate_reuses_active_job(self, client, workspace, monkeypatch):
        # Re-submitting the identical ingest while the first job is still
        # running must reuse it, not stack a redundant job.
        import threading

        import okfsmith.parsers as parsers

        c, headers = client
        real_parse = parsers.parse_file
        started = threading.Event()
        release = threading.Event()

        def slow_parse(path, *a, **kw):
            started.set()
            assert release.wait(timeout=30), "worker was not released"
            return real_parse(path, *a, **kw)

        monkeypatch.setattr(parsers, "parse_file", slow_parse)
        payload = {"files[]": ("dup-doc.md", SOURCE_TEXT.encode(), "text/markdown")}
        try:
            r1 = c.post("/api/v1/ingest", headers=headers, files=payload,
                        data={"new_bundle": "dup-target"})
            assert r1.status_code == 202
            assert started.wait(timeout=30), "worker never started parsing"
            r2 = c.post("/api/v1/ingest", headers=headers, files=payload,
                        data={"new_bundle": "dup-target"})
            assert r2.status_code == 202
            assert r2.json().get("reused") is True
            assert r2.json()["job_id"] == r1.json()["job_id"]
        finally:
            release.set()

    def test_settings_put_rejects_unknown_top_level(self, client):
        c, headers = client
        r = c.put(
            "/api/v1/settings",
            json={"config": {}, "default_provider_typo": "groq"},
            headers=headers,
        )
        assert r.status_code == 400
        _error_shape(r.json())
        assert "default_provider_typo" in r.json()["message"]

    def test_job_manager_retention_bounded(self):
        from okfsmith.dashboard import jobs as dash_jobs

        mgr = dash_jobs.JobManager(max_workers=2)
        try:
            def quick(job):
                job.finish("done")

            submitted = [mgr.submit("ingest", None, quick)
                         for _ in range(dash_jobs.MAX_RETAINED_JOBS + 50)]
            deadline = time.time() + 30
            while any(j.status not in ("done", "error") for j in submitted):
                assert time.time() < deadline, "jobs did not finish"
                time.sleep(0.05)
            assert len(mgr.list()) <= dash_jobs.MAX_RETAINED_JOBS
        finally:
            mgr.shutdown()

    def test_graph_edges_carry_dead_flag(self, client):
        c, headers = client
        bid = _bundle_id(c, headers)
        g = c.get(f"/api/v1/bundles/{bid}/graph", headers=headers).json()
        assert isinstance(g["nodes"], list) and isinstance(g["edges"], list)
        for e in g["edges"]:
            assert set(e) == {"from", "to", "dead"}
            assert isinstance(e["dead"], bool)

    def test_mcp_status_product_copy(self, client):
        c, headers = client
        s = c.get("/api/v1/mcp/status", headers=headers).json()
        assert "BundleTools" not in s["detail"], "implementation detail leaked into product copy"
        assert "tools" in s["detail"].lower() or "connected" in s["detail"].lower()
