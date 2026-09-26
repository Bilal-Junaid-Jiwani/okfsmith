"""Tests for the okfsmith Typer CLI.

Covers init/validate/list/read/graph against the ``.contract/fixtures``
bundles, plus error exits. Sibling slices (``okfsmith.validate``,
``okfsmith.parsers``, ``okfsmith.extract``, ``okfsmith.viz``,
``okfsmith.mcp_server``) are represented by lightweight stubs injected into
``sys.modules`` at their real submodule paths — this tests the CLI wiring
and the lazy-import contracts, not the slices themselves. The
"slice not landed" tests simulate an absent slice by blocking its import.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from okfsmith.cli.app import app
from okfsmith.core import Bundle, frontmatter
from okfsmith.validate import Finding, ValidationReport

runner = CliRunner()
WIDE = {"COLUMNS": "200"}  # keep rich tables from truncating concept rows
FIXTURES = Path(__file__).resolve().parents[1] / ".contract" / "fixtures"


# ---------------------------------------------------------------------------
# Stub-slice helpers
# ---------------------------------------------------------------------------


def _stub_check(bundle_path) -> ValidationReport:
    """Canned validator results keyed by fixture directory name (real types)."""
    name = Path(bundle_path).name

    def issue(code: str, file: str, message: str) -> Finding:
        return Finding(code=code, file=file, message=message, spec_ref="test")

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
    return ValidationReport(errors=errors, warnings=warnings)


@pytest.fixture()
def stub_validate(monkeypatch):
    """Inject a stub ``okfsmith.validate`` module honoring the lazy contract."""
    module = types.ModuleType("okfsmith.validate")
    module.check = _stub_check  # check(bundle_path) -> ValidationReport
    monkeypatch.setitem(sys.modules, "okfsmith.validate", module)
    return module


def _stub_parsers_modules(monkeypatch, ingest_no_llm):
    """Stub the parsers slice at its real submodule import paths."""
    parsers_mod = types.ModuleType("okfsmith.parsers")
    dedup_mod = types.ModuleType("okfsmith.parsers.dedup")
    inl_mod = types.ModuleType("okfsmith.parsers.ingest_no_llm")
    sectioning_mod = types.ModuleType("okfsmith.parsers.sectioning")

    seen: dict[str, str] = {}

    def sha256_of(path) -> str:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def already_ingested(bundle, digest: str) -> bool:
        return digest in seen

    def record_ingested(bundle, digest: str, source) -> None:
        seen[digest] = str(source)

    def parse_file(path):
        return SimpleNamespace(pages=[], meta={"source": str(path)})

    parsers_mod.parse_file = parse_file
    dedup_mod.sha256_of = sha256_of
    dedup_mod.already_ingested = already_ingested
    dedup_mod.record_ingested = record_ingested
    inl_mod.ingest_no_llm = ingest_no_llm
    sectioning_mod.TOO_SMALL_CHARS = 1000
    sectioning_mod.section = lambda parsed: SimpleNamespace(
        sections=[], too_small=False
    )

    monkeypatch.setitem(sys.modules, "okfsmith.parsers", parsers_mod)
    monkeypatch.setitem(sys.modules, "okfsmith.parsers.dedup", dedup_mod)
    monkeypatch.setitem(sys.modules, "okfsmith.parsers.ingest_no_llm", inl_mod)
    monkeypatch.setitem(sys.modules, "okfsmith.parsers.sectioning", sectioning_mod)
    return SimpleNamespace(seen=seen)


@pytest.fixture()
def stub_parsers(monkeypatch):
    """Inject stub parsers honoring the real no-LLM contract.

    ``ingest_no_llm(bundle, parsed, source_id)`` writes one draft concept
    per call and returns its id.
    """

    def ingest_no_llm(bundle: Bundle, parsed, source_id: str) -> list[str]:
        concept = bundle.write_concept(
            f"draft/{Path(source_id).stem}",
            {"type": "Draft", "title": f"Draft of {Path(source_id).name}"},
            f"Ingested from {source_id}.",
        )
        return [concept.id]

    return _stub_parsers_modules(monkeypatch, ingest_no_llm)


@pytest.fixture()
def stub_failing_parsers(monkeypatch):
    def ingest_no_llm(bundle: Bundle, parsed, source_id: str) -> list[str]:
        raise RuntimeError("simulated extraction failure")

    return _stub_parsers_modules(monkeypatch, ingest_no_llm)



@dataclass
class _StubSectionInput:
    title: str
    level: int
    text: str
    page_span: object = (1, 1)
    tables: list = field(default_factory=list)
    source_id: str = ""
    source_path: str = ""
    doc_title: str = ""
    doc_summary: str = ""
    section_path: str = ""


@pytest.fixture()
def stub_extract(monkeypatch):
    """Inject a stub ``okfsmith.extract`` plus the parsers pieces it needs."""
    parsers_mod = types.ModuleType("okfsmith.parsers")
    sectioning_mod = types.ModuleType("okfsmith.parsers.sectioning")
    extract_mod = types.ModuleType("okfsmith.extract")

    class LLMUnavailableError(Exception):
        pass

    def parse_file(path):
        return SimpleNamespace(pages=[], meta={"source": str(path)})

    def section(parsed):
        return SimpleNamespace(
            sections=[
                SimpleNamespace(
                    title="Intro", level=1, text="body text", page_span=(1, 1), tables=[]
                )
            ],
            too_small=False,
        )

    calls: list[dict] = []

    def run(bundle, sections, *, model=None, provider=None, base_url=None, api_key=None, verify=True):
        calls.append(
            {
                "n_sections": len(sections),
                "model": model,
                "provider": provider,
                "titles": [s.title for s in sections],
                "source_ids": [s.source_id for s in sections],
            }
        )
        concept = bundle.write_concept(
            "extracted/doc",
            {"type": "Extracted", "title": "Doc"},
            "Extracted body.",
        )
        return [concept.id]

    parsers_mod.parse_file = parse_file
    sectioning_mod.section = section
    extract_mod.SectionInput = _StubSectionInput
    extract_mod.run = run
    extract_mod.LLMUnavailableError = LLMUnavailableError

    monkeypatch.setitem(sys.modules, "okfsmith.parsers", parsers_mod)
    monkeypatch.setitem(sys.modules, "okfsmith.parsers.sectioning", sectioning_mod)
    monkeypatch.setitem(sys.modules, "okfsmith.extract", extract_mod)
    # The ingest command always loads sha256_of from okfsmith.parsers.dedup
    # (per-file digest shown in the summary table); stub it so test_cli.py
    # does not depend on another test module importing the real one first.
    dedup_mod = types.ModuleType("okfsmith.parsers.dedup")
    dedup_mod.sha256_of = lambda path: hashlib.sha256(
        Path(path).read_bytes()
    ).hexdigest()
    monkeypatch.setitem(sys.modules, "okfsmith.parsers.dedup", dedup_mod)
    return SimpleNamespace(calls=calls, LLMUnavailableError=LLMUnavailableError)


@pytest.fixture()
def stub_extract_unavailable(stub_extract, monkeypatch):
    """Same as stub_extract, but run() raises LLMUnavailableError."""

    def run(bundle, sections, *, model=None, provider=None, base_url=None, api_key=None, verify=True):
        raise stub_extract.LLMUnavailableError(
            "no LLM endpoint reachable: start Ollama (`ollama serve`) "
            "or set OKFSMITH_MODEL / OPENAI_API_KEY"
        )

    sys.modules["okfsmith.extract"].run = run
    return stub_extract


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


def _hide_slice(monkeypatch, dotted: str):
    """Simulate a slice that is not installed: block its import entirely."""
    real_import_module = importlib.import_module

    def fake_import_module(name, *args, **kwargs):
        if name == dotted or name.startswith(dotted + "."):
            raise ModuleNotFoundError(f"No module named '{dotted}'", name=dotted)
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)
    for mod in [m for m in sys.modules if m == dotted or m.startswith(dotted + ".")]:
        monkeypatch.delitem(sys.modules, mod, raising=False)


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
    # --force without --yes asks for confirmation; declining aborts
    result = runner.invoke(app, ["init", str(target), "--force"], input="n\n")
    assert result.exit_code == 1
    assert not (target / "index.md").is_file()
    # --force --yes proceeds non-interactively
    result = runner.invoke(app, ["init", str(target), "--force", "--yes"])
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
    assert payload["status"] == "conformant"
    assert payload["errors"] == []
    assert payload["warnings"][0]["code"] == "W001"
    assert payload["error_count"] == 0
    assert payload["warning_count"] == 1
    assert isinstance(payload["concepts"], int)


def test_validate_strict_treats_warnings_as_failures(stub_validate):
    plain = runner.invoke(app, ["validate", str(FIXTURES / "warn-dead-link")])
    assert plain.exit_code == 0, plain.output
    strict = runner.invoke(
        app, ["validate", str(FIXTURES / "warn-dead-link"), "--strict"]
    )
    assert strict.exit_code == 1, strict.output


def test_validate_unknown_format(stub_validate):
    # Invalid --format values are usage errors (exit 2).
    result = runner.invoke(
        app, ["validate", str(FIXTURES / "valid"), "--format", "yaml"]
    )
    assert result.exit_code == 2


def test_validate_missing_directory():
    result = runner.invoke(app, ["validate", "/does/not/exist"])
    assert result.exit_code == 1


def test_validate_without_slice_landed(monkeypatch):
    # okfsmith.validate is not installed: clean error, exit 1.
    _hide_slice(monkeypatch, "okfsmith.validate")
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


def test_graph_html_without_slice_landed(monkeypatch):
    _hide_slice(monkeypatch, "okfsmith.viz")
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
    # Invalid --format values are usage errors (exit 2).
    result = runner.invoke(
        app, ["graph", str(FIXTURES / "valid"), "--format", "svg"]
    )
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# ingest (stub parsers/extract — tests CLI wiring, not extraction itself)
# ---------------------------------------------------------------------------


def test_ingest_missing_source(tmp_path):
    result = runner.invoke(
        app, ["ingest", str(tmp_path / "b"), str(tmp_path / "nope.txt")]
    )
    assert result.exit_code == 1


def test_ingest_no_llm_without_slice_landed(monkeypatch, tmp_path):
    src = tmp_path / "doc.txt"
    src.write_text("hello", encoding="utf-8")
    _hide_slice(monkeypatch, "okfsmith.parsers")
    result = runner.invoke(
        app, ["ingest", str(tmp_path / "b"), str(src), "--no-llm"]
    )
    assert result.exit_code == 1
    assert "not available" in result.output


def test_ingest_no_llm_with_stub_parsers(stub_parsers, tmp_path):
    src = tmp_path / "doc.txt"
    src.write_text("hello", encoding="utf-8")
    bundle_dir = tmp_path / "bundle"
    result = runner.invoke(
        app, ["ingest", str(bundle_dir), str(src), "--no-llm"]
    )
    assert result.exit_code == 0, result.output
    assert (bundle_dir / "draft" / "doc.md").is_file()
    # dedup manifest recorded the source
    assert len(stub_parsers.seen) == 1
    # index refreshed and log appended
    assert (bundle_dir / "index.md").is_file()
    assert "**Update**" in (bundle_dir / "log.md").read_text(encoding="utf-8")


def test_ingest_no_llm_skips_already_ingested(stub_parsers, tmp_path):
    src = tmp_path / "doc.txt"
    src.write_text("hello", encoding="utf-8")
    bundle_dir = tmp_path / "bundle"
    first = runner.invoke(
        app, ["ingest", str(bundle_dir), str(src), "--no-llm"]
    )
    assert first.exit_code == 0, first.output
    second = runner.invoke(
        app, ["ingest", str(bundle_dir), str(src), "--no-llm"], env=WIDE
    )
    assert second.exit_code == 0, second.output
    assert "already ingested" in second.output
    assert "Wrote" not in second.output  # nothing new created


def test_ingest_directory_recursive(stub_parsers, tmp_path):
    srcdir = tmp_path / "src"
    (srcdir / "sub").mkdir(parents=True)
    (srcdir / "a.txt").write_text("a", encoding="utf-8")
    (srcdir / "sub" / "b.txt").write_text("b", encoding="utf-8")
    bundle_dir = tmp_path / "bundle"

    shallow = runner.invoke(
        app, ["ingest", str(bundle_dir), str(srcdir), "--no-llm"]
    )
    assert shallow.exit_code == 0, shallow.output
    assert (bundle_dir / "draft" / "a.md").is_file()
    assert not (bundle_dir / "draft" / "b.md").is_file()

    deep = runner.invoke(
        app,
        ["ingest", str(bundle_dir), str(srcdir), "--no-llm", "--recursive"],
    )
    assert deep.exit_code == 0, deep.output
    assert (bundle_dir / "draft" / "b.md").is_file()


def test_ingest_failure_row_escapes_rich_markup(monkeypatch, tmp_path):
    # Untrusted exception text containing Rich markup must render literally —
    # no markup injection, no crash. One good + one failing source so the
    # summary table (with the escaped row) is printed.
    def ingest_no_llm(bundle: Bundle, parsed, source_id: str) -> list[str]:
        if source_id.endswith("bad.txt"):
            raise RuntimeError("[bold]boom[/bold]")
        concept = bundle.write_concept(
            f"draft/{Path(source_id).stem}",
            {"type": "Draft", "title": "x"},
            "body",
        )
        return [concept.id]

    _stub_parsers_modules(monkeypatch, ingest_no_llm)
    good = tmp_path / "good.txt"
    bad = tmp_path / "bad.txt"
    good.write_text("hello", encoding="utf-8")
    bad.write_text("boom", encoding="utf-8")
    result = runner.invoke(
        app,
        ["ingest", str(tmp_path / "b"), str(good), str(bad), "--no-llm"],
        env=WIDE,
    )
    # Partial failure: warning is printed, exit stays 0 (something was ingested).
    assert result.exit_code == 0, result.output
    # Rich escape() renders the brackets literally (backslashes), never as markup.
    assert "\\[bold]boom\\[/bold]" in result.output
    assert "Traceback" not in result.output


def test_ingest_total_failure_exits_1(stub_failing_parsers, tmp_path):
    src = tmp_path / "doc.txt"
    src.write_text("hello", encoding="utf-8")
    result = runner.invoke(
        app, ["ingest", str(tmp_path / "b"), str(src), "--no-llm"]
    )
    assert result.exit_code == 1
    assert "all inputs failed" in result.output


def test_ingest_llm_path_without_slice_landed(monkeypatch, tmp_path):
    src = tmp_path / "doc.txt"
    src.write_text("hello", encoding="utf-8")
    _hide_slice(monkeypatch, "okfsmith.extract")
    result = runner.invoke(
        app, ["ingest", str(tmp_path / "b"), str(src)]
    )
    assert result.exit_code == 1
    assert "not available" in result.output


def test_ingest_llm_path_wires_sections(stub_extract, tmp_path):
    src = tmp_path / "doc.txt"
    src.write_text("hello", encoding="utf-8")
    bundle_dir = tmp_path / "bundle"
    result = runner.invoke(
        app,
        ["ingest", str(bundle_dir), str(src), "--model", "test-model"],
    )
    assert result.exit_code == 0, result.output
    assert len(stub_extract.calls) == 1
    call = stub_extract.calls[0]
    assert call["model"] == "test-model"
    assert call["n_sections"] == 1
    assert call["titles"] == ["Intro"]
    assert call["source_ids"] == [str(src)]
    assert (bundle_dir / "extracted" / "doc.md").is_file()
    assert "**Update**" in (bundle_dir / "log.md").read_text(encoding="utf-8")


def test_ingest_llm_unavailable_clean_error(stub_extract_unavailable, tmp_path):
    src = tmp_path / "doc.txt"
    src.write_text("hello", encoding="utf-8")
    result = runner.invoke(
        app, ["ingest", str(tmp_path / "b"), str(src)]
    )
    assert result.exit_code == 1
    assert "LLM unavailable" in result.output
    assert "Traceback" not in result.output


# ---------------------------------------------------------------------------
# mcp
# ---------------------------------------------------------------------------


def test_mcp_without_slice_landed(monkeypatch, tmp_path):
    _hide_slice(monkeypatch, "okfsmith.mcp_server")
    result = runner.invoke(app, ["mcp", str(FIXTURES / "valid")])
    assert result.exit_code == 1
    assert "not available" in result.output


def test_mcp_with_stub_server(stub_mcp, tmp_path):
    result = runner.invoke(
        app, ["mcp", str(FIXTURES / "valid"), "--transport", "stdio"]
    )
    assert result.exit_code == 0, result.output
    assert stub_mcp.calls == [(str(FIXTURES / "valid"), "stdio")]


def test_mcp_missing_bundle():
    result = runner.invoke(app, ["mcp", "/does/not/exist"])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# New CLI contract (positional bundle, constrained choices, stable errors)
# ---------------------------------------------------------------------------


def test_bare_invocation_prints_help():
    result = runner.invoke(app, [])
    assert result.exit_code == 0, result.output
    assert "init" in result.output
    assert "ingest" in result.output


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0, result.output
    assert "okfsmith" in result.output


def test_model_with_no_llm_conflicts(tmp_path):
    src = tmp_path / "doc.txt"
    src.write_text("hello", encoding="utf-8")
    result = runner.invoke(
        app,
        ["ingest", str(tmp_path / "b"), str(src), "--no-llm", "--model", "x"],
    )
    assert result.exit_code == 2


def test_validate_not_a_bundle(tmp_path):
    result = runner.invoke(app, ["validate", str(tmp_path)])
    assert result.exit_code == 1
    assert "bundle" in result.output.lower()


def test_ingest_dry_run_writes_nothing(stub_parsers, tmp_path):
    src = tmp_path / "doc.txt"
    src.write_text("hello", encoding="utf-8")
    bundle_dir = tmp_path / "bundle"
    result = runner.invoke(
        app, ["ingest", str(bundle_dir), str(src), "--no-llm", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert "dry run" in result.output.lower()
    assert not (bundle_dir / "draft").exists()


def test_ingest_quiet(stub_parsers, tmp_path):
    src = tmp_path / "doc.txt"
    src.write_text("hello", encoding="utf-8")
    bundle_dir = tmp_path / "bundle"
    result = runner.invoke(
        app, ["ingest", str(bundle_dir), str(src), "--no-llm", "--quiet"]
    )
    assert result.exit_code == 0, result.output
    assert "ingested" in result.output


def test_ingest_multiple_sources(stub_parsers, tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("a", encoding="utf-8")
    b.write_text("b", encoding="utf-8")
    bundle_dir = tmp_path / "bundle"
    result = runner.invoke(
        app, ["ingest", str(bundle_dir), str(a), str(b), "--no-llm"]
    )
    assert result.exit_code == 0, result.output
    assert (bundle_dir / "draft" / "a.md").is_file()
    assert (bundle_dir / "draft" / "b.md").is_file()


def test_read_json():
    result = runner.invoke(
        app, ["read", str(FIXTURES / "valid"), "finance/revenue", "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["id"] == "finance/revenue"
    assert payload["frontmatter"]["title"] == "Customer Orders"


def test_list_json():
    result = runner.invoke(
        app, ["list", str(FIXTURES / "valid"), "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["count"] == 4
    ids = {c["id"] for c in payload["concepts"]}
    assert "finance/revenue" in ids


def test_list_invalid_tier():
    result = runner.invoke(
        app, ["list", str(FIXTURES / "valid"), "--tier", "bogus"]
    )
    assert result.exit_code == 2


def test_mcp_invalid_transport():
    result = runner.invoke(
        app, ["mcp", str(FIXTURES / "valid"), "--transport", "bogus"]
    )
    assert result.exit_code == 2


def test_doctor():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "okfsmith doctor" in result.output
    assert "python" in result.output.lower()


def test_error_codes_are_stable():
    result = runner.invoke(app, ["validate", "/does/not/exist"])
    assert result.exit_code == 1
    assert "error [bundle-not-found]" in result.output


def test_ingest_skips_reserved_files_in_directory_scan(tmp_path):
    """index.md / log.md are bundle infrastructure, never knowledge sources."""
    from okfsmith.cli.commands import _collect_inputs

    src = tmp_path / "docs"
    src.mkdir()
    (src / "index.md").write_text("# index")
    (src / "log.md").write_text("# log")
    (src / "notes.md").write_text("# notes")
    collected = _collect_inputs(src, recursive=False)
    assert collected == [src / "notes.md"]

    # ... but an explicitly named file is still honored (explicit > heuristic).
    assert _collect_inputs(src / "index.md", recursive=False) == [src / "index.md"]


def test_read_missing_concept_error_shows_path_not_repr(tmp_path):
    """Error messages must show the bundle path, never a repr() of internals."""
    bdir = tmp_path / "kb"
    result = runner.invoke(app, ["init", str(bdir)])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["read", str(bdir), "nope/missing"])
    assert result.exit_code == 1
    assert f"not found in '{bdir}'" in result.output
    assert "Bundle object at" not in result.output


def test_no_bundle_repr_leaks_in_user_output(tmp_path):
    """User-facing output must show bundle paths, never '<...Bundle object at ...>'."""
    bdir = tmp_path / "kb"
    result = runner.invoke(app, ["init", str(bdir)])
    assert result.exit_code == 0, result.output
    assert "Bundle object at" not in result.output
    assert str(bdir) in result.output

    result = runner.invoke(app, ["list", str(bdir)])
    assert result.exit_code == 0, result.output
    assert "Bundle object at" not in result.output

    result = runner.invoke(app, ["read", str(bdir), "nope/missing"])
    assert result.exit_code == 1
    assert "Bundle object at" not in result.output


@pytest.fixture()
def stub_too_small_parsers(monkeypatch):
    """Stub parsers where every source is below the stub-prevention minimum."""

    def ingest_no_llm(bundle: Bundle, parsed, source_id: str) -> list[str]:
        raise AssertionError("must not be called for too-small sources")

    ns = _stub_parsers_modules(monkeypatch, ingest_no_llm)
    import sys as _sys

    mod = _sys.modules["okfsmith.parsers.sectioning"]
    mod.section = lambda parsed: SimpleNamespace(sections=[], too_small=True)
    return ns


def test_ingest_no_llm_too_small_reports_skip(stub_too_small_parsers, tmp_path):
    src = tmp_path / "tiny.txt"
    src.write_text("hello", encoding="utf-8")
    bundle_dir = tmp_path / "bundle"
    result = runner.invoke(
        app, ["ingest", str(bundle_dir), str(src), "--no-llm"], env=WIDE
    )
    assert result.exit_code == 0, result.output
    assert "below 1000-char minimum" in result.output
    assert "ingested 0 concept(s)" in result.output
    # Not recorded as ingested: a retry must repeat the reason, not claim
    # "already ingested".
    assert len(stub_too_small_parsers.seen) == 0
    second = runner.invoke(
        app, ["ingest", str(bundle_dir), str(src), "--no-llm"], env=WIDE
    )
    assert second.exit_code == 0, second.output
    assert "below 1000-char minimum" in second.output
    assert "already ingested" not in second.output


def test_ingest_dry_run_applies_too_small_rule(stub_too_small_parsers, tmp_path):
    src = tmp_path / "tiny.txt"
    src.write_text("hello", encoding="utf-8")
    bundle_dir = tmp_path / "bundle"
    result = runner.invoke(
        app, ["ingest", str(bundle_dir), str(src), "--no-llm", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert "would skip" in result.output
    assert "below 1000-char minimum" in result.output
    assert "draft concepts" not in result.output


def test_ingest_no_llm_zero_concepts_not_recorded(stub_parsers, tmp_path):
    """A source that yields no concepts is not marked ingested."""
    import sys as _sys

    _sys.modules["okfsmith.parsers.ingest_no_llm"].ingest_no_llm = (
        lambda bundle, parsed, source_id: []
    )
    src = tmp_path / "doc.txt"
    src.write_text("hello", encoding="utf-8")
    bundle_dir = tmp_path / "bundle"
    result = runner.invoke(
        app, ["ingest", str(bundle_dir), str(src), "--no-llm"], env=WIDE
    )
    assert result.exit_code == 0, result.output
    assert "no concepts created" in result.output
    assert len(stub_parsers.seen) == 0


def test_mcp_missing_extra_no_traceback(monkeypatch, tmp_path):
    """`okfsmith mcp` without fastmcp → stable error/hint, never a traceback."""
    import sys as _sys
    import types

    bundle_dir = tmp_path / "bundle"
    (bundle_dir / "draft").mkdir(parents=True)
    (bundle_dir / "index.md").write_text("# Index\n", encoding="utf-8")

    server_mod = types.ModuleType("okfsmith.mcp_server")

    def serve(bundle, transport):
        raise RuntimeError(
            "The MCP server requires the 'mcp' extra: "
            'install it with `pip install "okfsmith[mcp]"`.'
        )

    server_mod.serve = serve
    monkeypatch.setitem(_sys.modules, "okfsmith.mcp_server", server_mod)

    result = runner.invoke(app, ["mcp", str(bundle_dir)])
    assert result.exit_code == 1, result.output
    assert "error [missing-extra]:" in result.output
    assert "pip install" in result.output
    assert "Traceback" not in result.output
