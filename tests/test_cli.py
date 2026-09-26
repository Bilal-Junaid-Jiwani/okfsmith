"""Tests for the okfsmith Typer CLI.

Covers init/validate/list/read/graph against the ``.contract/fixtures``
bundles, plus error exits. Sibling slices that have not landed on this branch
(``okfsmith.validate``, ``okfsmith.parsers``, ``okfsmith.viz``,
``okfsmith.mcp_server``) are represented by lightweight stubs injected into
``sys.modules`` — this tests the CLI wiring and the documented lazy-import
contracts, not the slices themselves.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

from okfsmith.cli.app import app
from okfsmith.core import Bundle
from okfsmith.core import frontmatter

runner = CliRunner()
WIDE = {"COLUMNS": "200"}  # keep rich tables from truncating concept rows
FIXTURES = Path(__file__).resolve().parents[1] / ".contract" / "fixtures"


# ---------------------------------------------------------------------------
# Stub-slice helpers
# ---------------------------------------------------------------------------


class _CheckResult:
    def __init__(self, errors: list[dict], warnings: list[dict]) -> None:
        self.errors = errors
        self.warnings = warnings


def _stub_check(bundle_path) -> _CheckResult:
    """Canned validator results keyed by fixture directory name."""
    name = Path(bundle_path).name

    def issue(code: str, file: str, message: str) -> dict:
        return {"code": code, "file": file, "message": message, "spec": "test"}

    canned = {
        "err-no-frontmatter": ([issue("E001", "bad.md", "no frontmatter block")], []),
        "err-empty-type": ([issue("E002", "bad.md", "empty type")], []),
        "err-bad-index": ([issue("E003", "index.md", "bad index frontmatter")], []),
        "err-bad-log": ([issue("E004", "log.md", "bad log heading")], []),
        "warn-dead-link": ([], [issue("W001", "linked.md", "broken link")]),
        "warn-orphan": ([], [issue("W002", "orphan.md", "orphan concept")]),
        "legacy-v01": (
            [],
            [
                issue("W012", "old.md", "legacy timestamp"),
                issue("W012", "old.md", "legacy citations"),
            ],
        ),
    }
    errors, warnings = canned.get(name, ([], []))
    return _CheckResult(errors, warnings)


@pytest.fixture()
def stub_validate(monkeypatch):
    """Inject a stub ``okfsmith.validate`` module honoring the lazy contract."""
    module = types.ModuleType("okfsmith.validate")
    module.check = _stub_check  # check(bundle_path) -> .errors / .warnings
    monkeypatch.setitem(sys.modules, "okfsmith.validate", module)
    return module


@pytest.fixture()
def stub_parsers(monkeypatch, tmp_path):
    """Inject a stub ``okfsmith.parsers.ingest_no_llm`` that writes drafts."""
    module = types.ModuleType("okfsmith.parsers")

    def ingest_no_llm(sources: list[Path], bundle: Bundle) -> list:
        created = []
        for src in sources:
            created.append(
                bundle.write_concept(
                    f"draft/{src.stem}",
                    {"type": "Draft", "title": f"Draft of {src.name}"},
                    f"Ingested from {src.name}.",
                )
            )
        return created

    module.ingest_no_llm = ingest_no_llm
    monkeypatch.setitem(sys.modules, "okfsmith.parsers", module)
    return module


@pytest.fixture()
def stub_failing_parsers(monkeypatch):
    module = types.ModuleType("okfsmith.parsers")

    def ingest_no_llm(sources: list[Path], bundle: Bundle) -> list:
        raise RuntimeError("simulated extraction failure")

    module.ingest_no_llm = ingest_no_llm
    monkeypatch.setitem(sys.modules, "okfsmith.parsers", module)
    return module


@pytest.fixture()
def stub_viz(monkeypatch):
    module = types.ModuleType("okfsmith.viz")

    def render_html(root: Path, output: Path) -> Path:
        output = Path(output)
        output.write_text("<html>stub viz</html>", encoding="utf-8")
        return output

    module.render_html = render_html
    monkeypatch.setitem(sys.modules, "okfsmith.viz", module)
    return module


@pytest.fixture()
def stub_mcp(monkeypatch):
    module = types.ModuleType("okfsmith.mcp_server")
    calls: list[tuple] = []

    def serve(bundle_path, transport: str = "stdio") -> None:
        calls.append((str(bundle_path), transport))

    module.serve = serve
    module.calls = calls
    monkeypatch.setitem(sys.modules, "okfsmith.mcp_server", module)
    return module


# ---------------------------------------------------------------------------
# version / init
# ---------------------------------------------------------------------------


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "okfsmith" in result.output


def test_init_creates_bundle(tmp_path):
    target = tmp_path / "bundle"
    result = runner.invoke(app, ["init", str(target)])
    assert result.exit_code == 0, result.output
    index_text = (target / "index.md").read_text(encoding="utf-8")
    fm, _ = frontmatter.parse_frontmatter(index_text)
    assert fm == {"okf_version": "0.2"}
    log = (target / "log.md").read_text(encoding="utf-8")
    assert "**Creation**" in log


def test_init_refuses_nonempty_dir(tmp_path):
    target = tmp_path / "bundle"
    target.mkdir()
    (target / "existing.txt").write_text("x", encoding="utf-8")
    result = runner.invoke(app, ["init", str(target)])
    assert result.exit_code == 1
    assert "not empty" in result.output
    # --force proceeds
    result = runner.invoke(app, ["init", str(target), "--force"])
    assert result.exit_code == 0, result.output
    assert (target / "index.md").is_file()


def test_init_creates_nested_parents(tmp_path):
    target = tmp_path / "a" / "b" / "bundle"
    result = runner.invoke(app, ["init", str(target)])
    assert result.exit_code == 0, result.output
    assert (target / "index.md").is_file()


# ---------------------------------------------------------------------------
# validate (stub validator — tests CLI wiring, not the validator itself)
# ---------------------------------------------------------------------------


def test_validate_valid_bundle(stub_validate):
    result = runner.invoke(app, ["validate", str(FIXTURES / "valid")])
    assert result.exit_code == 0, result.output
    assert "Conformant" in result.output


@pytest.mark.parametrize(
    "fixture", ["err-no-frontmatter", "err-empty-type", "err-bad-index", "err-bad-log"]
)
def test_validate_error_fixtures_exit_1(stub_validate, fixture):
    result = runner.invoke(app, ["validate", str(FIXTURES / fixture)])
    assert result.exit_code == 1, result.output


def test_validate_error_code_shown(stub_validate):
    result = runner.invoke(app, ["validate", str(FIXTURES / "err-no-frontmatter")])
    assert "E001" in result.output


def test_validate_json_format(stub_validate):
    result = runner.invoke(
        app, ["validate", str(FIXTURES / "warn-dead-link"), "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["errors"] == []
    assert payload["warnings"][0]["code"] == "W001"


def test_validate_strict_treats_warnings_as_failures(stub_validate):
    plain = runner.invoke(app, ["validate", str(FIXTURES / "warn-dead-link")])
    assert plain.exit_code == 0, plain.output
    strict = runner.invoke(
        app, ["validate", str(FIXTURES / "warn-dead-link"), "--strict"]
    )
    assert strict.exit_code == 1, strict.output


def test_validate_unknown_format(stub_validate):
    result = runner.invoke(
        app, ["validate", str(FIXTURES / "valid"), "--format", "yaml"]
    )
    assert result.exit_code == 1


def test_validate_missing_directory():
    result = runner.invoke(app, ["validate", "/does/not/exist"])
    assert result.exit_code == 1


def test_validate_without_slice_landed():
    # okfsmith.validate has not landed on this branch: clean error, exit 1.
    assert "okfsmith.validate" not in sys.modules
    result = runner.invoke(app, ["validate", str(FIXTURES / "valid")])
    assert result.exit_code == 1
    assert "not available" in result.output


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_shows_concepts():
    result = runner.invoke(app, ["list", str(FIXTURES / "valid")], env=WIDE)
    assert result.exit_code == 0, result.output
    for concept_id in ("finance/revenue", "finance/profit", "incidents/playbook"):
        assert concept_id in result.output
    assert "human-reviewed" in result.output
    assert "4 concept(s)" in result.output


def test_list_filter_by_type():
    result = runner.invoke(
        app, ["list", str(FIXTURES / "valid"), "--type", "BigQuery Table"], env=WIDE
    )
    assert result.exit_code == 0, result.output
    assert "finance/revenue" in result.output
    assert "incidents/playbook" not in result.output
    assert "1 concept(s)" in result.output


def test_list_filter_by_tier():
    result = runner.invoke(
        app, ["list", str(FIXTURES / "valid"), "--tier", "unverified"], env=WIDE
    )
    assert result.exit_code == 0, result.output
    assert "incidents/playbook" in result.output
    assert "finance/revenue" not in result.output


def test_list_missing_directory():
    result = runner.invoke(app, ["list", "/does/not/exist"])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


def test_read_concept():
    result = runner.invoke(app, ["read", str(FIXTURES / "valid"), "finance/revenue"])
    assert result.exit_code == 0, result.output
    assert "Customer Orders" in result.output
    assert "type: BigQuery Table" in result.output


def test_read_missing_concept():
    result = runner.invoke(app, ["read", str(FIXTURES / "valid"), "nope/missing"])
    assert result.exit_code == 1
    assert "not found" in result.output


# ---------------------------------------------------------------------------
# graph
# ---------------------------------------------------------------------------


def test_graph_json():
    result = runner.invoke(
        app, ["graph", str(FIXTURES / "valid"), "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    node_ids = {n["id"] for n in payload["nodes"]}
    assert {"finance/revenue", "finance/profit", "incidents/playbook"} <= node_ids
    node = next(n for n in payload["nodes"] if n["id"] == "finance/revenue")
    assert node["type"] == "BigQuery Table"
    assert node["title"] == "Customer Orders"
    # incidents/playbook links to /finance/revenue (bundle-absolute link)
    assert "finance/revenue" in payload["adjacency"]["incidents/playbook"]


def test_graph_mermaid():
    result = runner.invoke(
        app, ["graph", str(FIXTURES / "valid"), "--format", "mermaid"]
    )
    assert result.exit_code == 0, result.output
    assert "flowchart LR" in result.output
    assert "-->" in result.output


def test_graph_text_reports_dead_link():
    result = runner.invoke(app, ["graph", str(FIXTURES / "warn-dead-link")])
    assert result.exit_code == 0, result.output
    assert "Dead links (1)" in result.output
    assert "/finance/does-not-exist" in result.output


def test_graph_text_reports_orphan():
    result = runner.invoke(app, ["graph", str(FIXTURES / "warn-orphan")])
    assert result.exit_code == 0, result.output
    assert "Orphans (1)" in result.output
    assert "orphan" in result.output


def test_graph_html_without_slice_landed(tmp_path):
    assert "okfsmith.viz" not in sys.modules
    result = runner.invoke(
        app, ["graph", str(FIXTURES / "valid"), "--format", "html"]
    )
    assert result.exit_code == 1
    assert "not available" in result.output


def test_graph_html_with_stub_viz(stub_viz, tmp_path):
    out = tmp_path / "custom.html"
    result = runner.invoke(
        app,
        ["graph", str(FIXTURES / "valid"), "--format", "html", "--output", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert out.is_file()


def test_graph_html_default_output(stub_viz):
    result = runner.invoke(
        app, ["graph", str(FIXTURES / "valid"), "--format", "html"]
    )
    assert result.exit_code == 0, result.output
    assert (FIXTURES / "valid" / "viz.html").is_file()
    (FIXTURES / "valid" / "viz.html").unlink()  # don't pollute the fixture


def test_graph_unknown_format():
    result = runner.invoke(
        app, ["graph", str(FIXTURES / "valid"), "--format", "svg"]
    )
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# ingest (stub parsers — tests CLI wiring, not extraction itself)
# ---------------------------------------------------------------------------


def test_ingest_missing_source(tmp_path):
    result = runner.invoke(
        app, ["ingest", str(tmp_path / "nope.txt"), "--bundle", str(tmp_path / "b")]
    )
    assert result.exit_code == 1


def test_ingest_no_llm_without_slice_landed(tmp_path):
    src = tmp_path / "doc.txt"
    src.write_text("hello", encoding="utf-8")
    assert "okfsmith.parsers" not in sys.modules
    result = runner.invoke(
        app, ["ingest", str(src), "--bundle", str(tmp_path / "b"), "--no-llm"]
    )
    assert result.exit_code == 1
    assert "not available" in result.output


def test_ingest_no_llm_with_stub_parsers(stub_parsers, tmp_path):
    src = tmp_path / "doc.txt"
    src.write_text("hello", encoding="utf-8")
    bundle_dir = tmp_path / "bundle"
    result = runner.invoke(
        app, ["ingest", str(src), "--bundle", str(bundle_dir), "--no-llm"]
    )
    assert result.exit_code == 0, result.output
    assert (bundle_dir / "draft" / "doc.md").is_file()
    # index refreshed and log appended
    assert (bundle_dir / "index.md").is_file()
    assert "**Update**" in (bundle_dir / "log.md").read_text(encoding="utf-8")


def test_ingest_directory_recursive(stub_parsers, tmp_path):
    srcdir = tmp_path / "src"
    (srcdir / "sub").mkdir(parents=True)
    (srcdir / "a.txt").write_text("a", encoding="utf-8")
    (srcdir / "sub" / "b.txt").write_text("b", encoding="utf-8")
    bundle_dir = tmp_path / "bundle"

    shallow = runner.invoke(
        app, ["ingest", str(srcdir), "--bundle", str(bundle_dir), "--no-llm"]
    )
    assert shallow.exit_code == 0, shallow.output
    assert (bundle_dir / "draft" / "a.md").is_file()
    assert not (bundle_dir / "draft" / "b.md").is_file()

    deep = runner.invoke(
        app,
        ["ingest", str(srcdir), "--bundle", str(bundle_dir), "--no-llm", "--recursive"],
    )
    assert deep.exit_code == 0, deep.output
    assert (bundle_dir / "draft" / "b.md").is_file()


def test_ingest_total_failure_exits_1(stub_failing_parsers, tmp_path):
    src = tmp_path / "doc.txt"
    src.write_text("hello", encoding="utf-8")
    result = runner.invoke(
        app, ["ingest", str(src), "--bundle", str(tmp_path / "b"), "--no-llm"]
    )
    assert result.exit_code == 1
    assert "all inputs failed" in result.output


def test_ingest_llm_path_without_slice_landed(tmp_path):
    src = tmp_path / "doc.txt"
    src.write_text("hello", encoding="utf-8")
    assert "okfsmith.extract" not in sys.modules
    result = runner.invoke(
        app, ["ingest", str(src), "--bundle", str(tmp_path / "b")]
    )
    assert result.exit_code == 1
    assert "not available" in result.output


# ---------------------------------------------------------------------------
# mcp
# ---------------------------------------------------------------------------


def test_mcp_without_slice_landed(tmp_path):
    assert "okfsmith.mcp_server" not in sys.modules
    result = runner.invoke(app, ["mcp", "--bundle", str(tmp_path)])
    assert result.exit_code == 1
    assert "not available" in result.output


def test_mcp_with_stub_server(stub_mcp, tmp_path):
    result = runner.invoke(
        app, ["mcp", "--bundle", str(tmp_path), "--transport", "stdio"]
    )
    assert result.exit_code == 0, result.output
    assert stub_mcp.calls == [(str(tmp_path), "stdio")]


def test_mcp_missing_bundle():
    result = runner.invoke(app, ["mcp", "--bundle", "/does/not/exist"])
    assert result.exit_code == 1
