"""Tests for the ``search`` command and CLI QA bug fixes.

Covers the feature spec (``okfsmith search``: table + JSON output, filters,
exit codes) and regression tests for QA items H1/H7/H8/H9/H10/H11, M2/M7/M18/M19,
L1/L24/L25, and the C8 ``BundleError`` -> ``error [io-error]`` contract.

Conventions mirror ``tests/test_cli.py``: sibling slices are stubbed in
``sys.modules`` at their real paths. The search engine (``okfsmith.search``,
built concurrently by another agent) is stubbed with a canned stand-in so
the CLI wiring is tested independently of the engine; one test asserts the
clean ``search-unavailable`` path while the engine is not landed.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from okfsmith.cli import commands as _commands
from okfsmith.cli.app import app
from okfsmith.core.bundle import Bundle, Concept
from okfsmith.validate import Finding, ValidationReport

runner = CliRunner()
WIDE = {"COLUMNS": "200"}  # keep rich tables from truncating concept rows
FIXTURES = Path(__file__).resolve().parents[1] / ".contract" / "fixtures"


def _no_traceback(result) -> None:
    """Assert a clean CLI failure: no traceback leaked to the user."""
    assert "Traceback" not in result.output, result.output
    assert "Traceback" not in (result.stderr or ""), result.stderr


# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------


def _make_bundle(tmp_path: Path, name: str = "kb") -> Path:
    """A minimal on-disk bundle (index.md makes it look like a bundle)."""
    bundle = tmp_path / name
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "index.md").write_text("# Index\n", encoding="utf-8")
    return bundle


def _stub_search(monkeypatch, hits):
    """Inject a canned ``okfsmith.search`` engine.

    *hits* is the list returned as ``[(score, Concept), ...]``; calls are
    recorded on the returned namespace. Provides both ``search_bundle``
    and ``search_bundle_detailed`` (the latter returns a small namespace
    with ``hits`` / ``as_of`` / ``superseded_hidden``, mirroring
    ``TemporalSearchResult``).
    """
    from datetime import datetime, timezone

    module = types.ModuleType("okfsmith.search")
    calls: list[dict] = []

    def search_bundle(bundle, query, limit=10):
        calls.append({"bundle": bundle, "query": query, "limit": limit})
        return hits

    def search_bundle_detailed(bundle, query, limit=10, *, as_of=None, include_superseded=False):
        calls.append(
            {
                "bundle": bundle,
                "query": query,
                "limit": limit,
                "as_of": as_of,
                "include_superseded": include_superseded,
            }
        )
        return SimpleNamespace(
            hits=hits,
            as_of=as_of or datetime.now(timezone.utc),
            superseded_hidden=0,
        )

    module.search_bundle = search_bundle
    module.search_bundle_detailed = search_bundle_detailed
    monkeypatch.setitem(sys.modules, "okfsmith.search", module)
    return SimpleNamespace(calls=calls)


def _concept(cid, type_="Note", title="", verified=None, body=""):
    fm: dict = {"type": type_, "title": title}
    if verified is not None:
        fm["verified"] = verified
    return Concept(
        id=cid, path=Path(f"/tmp/{cid}.md"), frontmatter=fm, body=body
    )


def _stub_validate(monkeypatch, errors=(), warnings=()):
    """Inject a stub ``okfsmith.validate`` honoring the lazy contract."""
    module = types.ModuleType("okfsmith.validate")

    def check(bundle_path):
        return ValidationReport(errors=list(errors), warnings=list(warnings))

    module.check = check
    monkeypatch.setitem(sys.modules, "okfsmith.validate", module)
    return module


def _stub_parsers(
    monkeypatch,
    *,
    parse_file=None,
    sha256_of=None,
    already_ingested=None,
    record_ingested=None,
    ingest_no_llm=None,
    too_small=False,
):
    """Stub the parsers slice; knobs allow failure injection per test."""
    parsers_mod = types.ModuleType("okfsmith.parsers")
    dedup_mod = types.ModuleType("okfsmith.parsers.dedup")
    inl_mod = types.ModuleType("okfsmith.parsers.ingest_no_llm")
    sectioning_mod = types.ModuleType("okfsmith.parsers.sectioning")
    seen: dict[str, str] = {}

    def default_sha256(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def default_parse(path):
        return SimpleNamespace(pages=[], meta={"source": str(path)})

    def default_ingest_no_llm(bundle, parsed, source_id):
        concept = bundle.write_concept(
            f"draft/{Path(source_id).stem}",
            {"type": "Draft", "title": f"Draft of {Path(source_id).name}"},
            f"Ingested from {source_id}.",
        )
        return [concept.id]

    parsers_mod.parse_file = parse_file or default_parse
    dedup_mod.sha256_of = sha256_of or default_sha256
    dedup_mod.already_ingested = (
        already_ingested or (lambda bundle, digest: digest in seen)
    )
    dedup_mod.record_ingested = record_ingested or (
        lambda bundle, digest, source: seen.__setitem__(digest, str(source))
    )
    inl_mod.ingest_no_llm = ingest_no_llm or default_ingest_no_llm
    sectioning_mod.TOO_SMALL_CHARS = 1000
    sectioning_mod.section = lambda parsed: SimpleNamespace(
        sections=[], too_small=too_small
    )

    monkeypatch.setitem(sys.modules, "okfsmith.parsers", parsers_mod)
    monkeypatch.setitem(sys.modules, "okfsmith.parsers.dedup", dedup_mod)
    monkeypatch.setitem(sys.modules, "okfsmith.parsers.ingest_no_llm", inl_mod)
    monkeypatch.setitem(sys.modules, "okfsmith.parsers.sectioning", sectioning_mod)
    return SimpleNamespace(seen=seen)


def _stub_viz(monkeypatch):
    module = types.ModuleType("okfsmith.viz")

    def render_html(root, output):
        output = Path(output)
        output.write_text("<html>stub viz</html>", encoding="utf-8")
        return output

    module.render_html = render_html
    monkeypatch.setitem(sys.modules, "okfsmith.viz", module)
    return module


# ---------------------------------------------------------------------------
# search command
# ---------------------------------------------------------------------------


def _search_hits():
    return [
        (9.5, _concept("notes/alpha", type_="Note", title="Alpha notes",
                        verified=[{"by": "human:alice"}])),
        (4.25, _concept("notes/beta-long-concept-id-that-must-not-truncate",
                        type_="Guide", title="Beta guide")),
        (1.0, _concept("notes/gamma", type_="Note", title="Gamma",
                       verified=[{"by": "process:nightly"}])),
    ]


def test_search_table_output(monkeypatch, tmp_path):
    stub = _stub_search(monkeypatch, _search_hits())
    bundle = _make_bundle(tmp_path)
    result = runner.invoke(
        app, ["search", str(bundle), "alpha notes"], env=WIDE
    )
    assert result.exit_code == 0, result.output
    for header in ("Score", "ID", "Type", "Title", "Tier"):
        assert header in result.output, result.output
    # IDs are never truncated.
    assert "notes/beta-long-concept-id-that-must-not-truncate" in result.output
    assert "human-reviewed" in result.output
    assert "3 results" in result.output
    assert stub.calls and stub.calls[0]["query"] == "alpha notes"
    assert stub.calls[0]["limit"] == 10


def test_search_json_output(monkeypatch, tmp_path):
    _stub_search(monkeypatch, _search_hits())
    bundle = _make_bundle(tmp_path)
    result = runner.invoke(
        app, ["search", str(bundle), "alpha", "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["query"] == "alpha"
    assert payload["count"] == 3
    assert len(payload["results"]) == 3
    first = payload["results"][0]
    assert first["id"] == "notes/alpha"
    assert first["type"] == "Note"
    assert first["title"] == "Alpha notes"
    assert first["tier"] == "human-reviewed"
    assert isinstance(first["score"], float)


def test_search_tier_filter(monkeypatch, tmp_path):
    _stub_search(monkeypatch, _search_hits())
    bundle = _make_bundle(tmp_path)
    result = runner.invoke(
        app,
        ["search", str(bundle), "notes", "--tier", "human-reviewed",
         "--format", "json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["count"] == 1
    assert payload["results"][0]["id"] == "notes/alpha"


def test_search_type_filter_case_insensitive(monkeypatch, tmp_path):
    _stub_search(monkeypatch, _search_hits())
    bundle = _make_bundle(tmp_path)
    result = runner.invoke(
        app,
        ["search", str(bundle), "notes", "--type", "guide", "--format", "json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["count"] == 1
    assert payload["results"][0]["type"] == "Guide"


def test_search_limit_short_flag(monkeypatch, tmp_path):
    stub = _stub_search(monkeypatch, _search_hits())
    bundle = _make_bundle(tmp_path)
    result = runner.invoke(app, ["search", str(bundle), "notes", "-n", "5"])
    assert result.exit_code == 0, result.output
    assert stub.calls[0]["limit"] == 5


def test_search_empty_query_exit_2(monkeypatch, tmp_path):
    _stub_search(monkeypatch, [])
    bundle = _make_bundle(tmp_path)
    for query in ("", "   "):
        result = runner.invoke(app, ["search", str(bundle), query])
        assert result.exit_code == 2, result.output


@pytest.mark.parametrize("limit", ["0", "-3"])
def test_search_bad_limit_exit_2(monkeypatch, tmp_path, limit):
    _stub_search(monkeypatch, [])
    bundle = _make_bundle(tmp_path)
    result = runner.invoke(
        app, ["search", str(bundle), "notes", "--limit", limit]
    )
    assert result.exit_code == 2, result.output


def test_search_bad_format_exit_2(monkeypatch, tmp_path):
    _stub_search(monkeypatch, [])
    bundle = _make_bundle(tmp_path)
    result = runner.invoke(
        app, ["search", str(bundle), "notes", "--format", "yaml"]
    )
    assert result.exit_code == 2, result.output


def test_search_bad_tier_exit_2(monkeypatch, tmp_path):
    _stub_search(monkeypatch, [])
    bundle = _make_bundle(tmp_path)
    result = runner.invoke(
        app, ["search", str(bundle), "notes", "--tier", "bogus"]
    )
    assert result.exit_code == 2, result.output


def test_search_missing_bundle(monkeypatch):
    _stub_search(monkeypatch, [])
    result = runner.invoke(app, ["search", "/does/not/exist", "notes"])
    assert result.exit_code == 1
    assert "error [bundle-not-found]" in result.output


def test_search_zero_results_exit_0_with_hint(monkeypatch, tmp_path):
    _stub_search(monkeypatch, [])
    bundle = _make_bundle(tmp_path)
    result = runner.invoke(app, ["search", str(bundle), "zzz-no-match"])
    assert result.exit_code == 0, result.output
    assert "0 results" in result.output
    assert "hint:" in (result.stderr or ""), result.output
    # JSON mode: still exit 0 with an empty results list.
    result = runner.invoke(
        app, ["search", str(bundle), "zzz-no-match", "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["query"] == "zzz-no-match"
    assert payload["results"] == []
    assert payload["count"] == 0
    assert payload["superseded_hidden"] == 0
    assert "as_of" in payload


@pytest.mark.skipif(
    importlib.util.find_spec("okfsmith.search") is not None,
    reason="real okfsmith.search engine is landed",
)
def test_search_unavailable_without_engine(monkeypatch, tmp_path):
    # While the search engine is not landed, the command fails cleanly —
    # never a traceback.
    monkeypatch.delitem(sys.modules, "okfsmith.search", raising=False)
    bundle = _make_bundle(tmp_path)
    result = runner.invoke(app, ["search", str(bundle), "notes"])
    assert result.exit_code == 1
    assert "error [search-unavailable]" in result.output
    _no_traceback(result)


# ---------------------------------------------------------------------------
# H1 — unreadable file must not abort the batch
# ---------------------------------------------------------------------------


def test_ingest_unreadable_file_does_not_abort_batch(monkeypatch, tmp_path):
    def flaky_sha256(path):
        if Path(path).name == "bad.txt":
            raise PermissionError(13, "Permission denied", str(path))
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    _stub_parsers(monkeypatch, sha256_of=flaky_sha256)
    srcdir = tmp_path / "src"
    srcdir.mkdir()
    (srcdir / "bad.txt").write_text("bad", encoding="utf-8")
    (srcdir / "good.txt").write_text("good", encoding="utf-8")
    bundle = tmp_path / "bundle"

    result = runner.invoke(
        app, ["ingest", str(bundle), str(srcdir), "--no-llm"]
    )
    assert result.exit_code == 0, result.output
    assert "failed" in result.output
    assert not isinstance(result.exception, PermissionError)
    _no_traceback(result)
    # The good file was still ingested.
    assert (bundle / "draft" / "good.md").is_file()
    assert "1 failed" in result.output


# ---------------------------------------------------------------------------
# H7 — graph --output must not clobber without --force
# ---------------------------------------------------------------------------


def test_graph_output_refuses_existing_file(tmp_path):
    out = tmp_path / "graph.json"
    out.write_text("precious", encoding="utf-8")
    result = runner.invoke(
        app,
        ["graph", str(FIXTURES / "valid"), "--format", "json",
         "--output", str(out)],
    )
    assert result.exit_code == 1
    assert "error [output-exists]" in result.output
    assert "hint:" in result.output
    assert out.read_text(encoding="utf-8") == "precious"
    _no_traceback(result)


def test_graph_output_force_overwrites(tmp_path):
    out = tmp_path / "graph.json"
    out.write_text("precious", encoding="utf-8")
    result = runner.invoke(
        app,
        ["graph", str(FIXTURES / "valid"), "--format", "json",
         "--output", str(out), "--force"],
    )
    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8") != "precious"


def test_graph_html_default_output_refuses_existing(monkeypatch, tmp_path):
    _stub_viz(monkeypatch)
    bundle = _make_bundle(tmp_path)
    viz = bundle / "viz.html"
    viz.write_text("precious", encoding="utf-8")
    result = runner.invoke(app, ["graph", str(bundle), "--format", "html"])
    assert result.exit_code == 1
    assert "error [output-exists]" in result.output
    assert viz.read_text(encoding="utf-8") == "precious"
    # ... and --force allows the default path too.
    result = runner.invoke(
        app, ["graph", str(bundle), "--format", "html", "--force"]
    )
    assert result.exit_code == 0, result.output
    assert viz.read_text(encoding="utf-8") != "precious"


# ---------------------------------------------------------------------------
# H8 — graph --output: missing parents created, directory target rejected
# ---------------------------------------------------------------------------


def test_graph_output_creates_missing_parents(tmp_path):
    out = tmp_path / "no-such-dir" / "nested" / "graph.json"
    result = runner.invoke(
        app,
        ["graph", str(FIXTURES / "valid"), "--format", "json",
         "--output", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert out.is_file()
    assert json.loads(out.read_text(encoding="utf-8"))["nodes"]


def test_graph_output_mermaid_creates_missing_parents(tmp_path):
    out = tmp_path / "no-such-dir" / "graph.mmd"
    result = runner.invoke(
        app,
        ["graph", str(FIXTURES / "valid"), "--format", "mermaid",
         "--output", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert out.is_file()


@pytest.mark.parametrize("fmt", ["json", "mermaid", "text"])
def test_graph_output_directory_target_rejected(tmp_path, fmt):
    outdir = tmp_path / "outdir"
    outdir.mkdir()
    result = runner.invoke(
        app,
        ["graph", str(FIXTURES / "valid"), "--format", fmt,
         "--output", str(outdir)],
    )
    assert result.exit_code == 1
    assert "error [invalid-output]" in result.output
    assert "hint:" in result.output
    _no_traceback(result)


# ---------------------------------------------------------------------------
# H9 — file-as-bundle for ingest
# ---------------------------------------------------------------------------


def test_ingest_bundle_path_is_file(monkeypatch, tmp_path):
    _stub_parsers(monkeypatch)
    afile = tmp_path / "afile"
    afile.write_text("x", encoding="utf-8")
    src = tmp_path / "doc.txt"
    src.write_text("hello", encoding="utf-8")
    result = runner.invoke(
        app, ["ingest", str(afile), str(src), "--no-llm"]
    )
    assert result.exit_code == 1
    assert "error [not-a-directory]" in result.output
    assert "hint:" in result.output
    _no_traceback(result)


# ---------------------------------------------------------------------------
# H10 — FIFO / non-file-non-dir as ingest source
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("source", ["fifo", "devzero"])
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Unix-specific: os.mkfifo and /dev/zero do not exist on Windows",
)
def test_ingest_non_file_source_rejected(monkeypatch, tmp_path, source):
    _stub_parsers(monkeypatch)
    bundle = tmp_path / "bundle"
    if source == "fifo":
        src = tmp_path / "p.fifo"
        os.mkfifo(src)
    else:
        src = Path("/dev/zero")
    result = runner.invoke(app, ["ingest", str(bundle), str(src), "--no-llm"])
    assert result.exit_code == 1
    assert "error [not-a-directory]" in result.output
    assert "hint:" in result.output
    _no_traceback(result)


# ---------------------------------------------------------------------------
# H11 — init I/O failures -> error [io-error]
# ---------------------------------------------------------------------------


def test_init_io_failure_clean_error(monkeypatch, tmp_path):
    def boom(self, *args, **kwargs):
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "mkdir", boom)
    result = runner.invoke(app, ["init", str(tmp_path / "kb")])
    assert result.exit_code == 1
    assert "error [io-error]" in result.output
    assert "hint:" in result.output
    _no_traceback(result)


# ---------------------------------------------------------------------------
# M2 — parse errors reported before the too-small check
# ---------------------------------------------------------------------------


def test_ingest_reports_parse_error_not_stub_prevention(monkeypatch, tmp_path):
    def parse_file(path):
        return SimpleNamespace(
            pages=[],
            meta={
                "source": str(path),
                "error": "RuntimeError: could not parse (boom)",
            },
        )

    _stub_parsers(monkeypatch, parse_file=parse_file, too_small=True)
    src = tmp_path / "doc.txt"
    src.write_text("hello", encoding="utf-8")
    result = runner.invoke(
        app, ["ingest", str(tmp_path / "bundle"), str(src), "--no-llm"],
        env=WIDE,
    )
    assert result.exit_code == 0, result.output
    assert "stub prevention" not in result.output
    assert "could not parse (boom)" in result.output


# ---------------------------------------------------------------------------
# M7 — --strict must not print "Conformant" while exiting 1
# ---------------------------------------------------------------------------


def test_validate_strict_does_not_print_conformant(monkeypatch, tmp_path):
    _stub_validate(
        monkeypatch,
        warnings=[Finding(code="W001", file="a.md", message="broken",
                          spec_ref="test")],
    )
    bundle = _make_bundle(tmp_path)
    strict = runner.invoke(app, ["validate", str(bundle), "--strict"])
    assert strict.exit_code == 1, strict.output
    assert "Conformant" not in strict.output
    assert "INVALID" in strict.output
    # Non-strict warnings-only still says Conformant and exits 0.
    plain = runner.invoke(app, ["validate", str(bundle)])
    assert plain.exit_code == 0, plain.output
    assert "Conformant" in plain.output


# ---------------------------------------------------------------------------
# M18 — dry run consults the dedup manifest
# ---------------------------------------------------------------------------


def test_dry_run_consults_dedup_manifest(monkeypatch, tmp_path):
    from okfsmith.parsers import dedup as real_dedup

    _stub_parsers(
        monkeypatch,
        sha256_of=real_dedup.sha256_of,
        already_ingested=real_dedup.already_ingested,
        record_ingested=real_dedup.record_ingested,
    )
    src = tmp_path / "doc.txt"
    src.write_text("hello", encoding="utf-8")
    bundle = tmp_path / "bundle"

    first = runner.invoke(
        app, ["ingest", str(bundle), str(src), "--no-llm"]
    )
    assert first.exit_code == 0, first.output
    manifest = bundle / ".okfsmith" / "manifest.json"
    assert manifest.is_file()

    dry = runner.invoke(
        app, ["ingest", str(bundle), str(src), "--no-llm", "--dry-run"]
    )
    assert dry.exit_code == 0, dry.output
    assert "already ingested" in dry.output
    assert "draft concepts" not in dry.output


# ---------------------------------------------------------------------------
# M19 — explicit office file without the extra fails loudly
# ---------------------------------------------------------------------------

_MISSING_EXTRA_ERROR = (
    "RuntimeError: markitdown is not installed; install okfsmith with the "
    "office extra (`pip install \"okfsmith[office]\"`) to parse this file type"
)


def _office_error_parsers(monkeypatch):
    def parse_file(path):
        return SimpleNamespace(
            pages=[], meta={"source": str(path), "error": _MISSING_EXTRA_ERROR}
        )

    return _stub_parsers(monkeypatch, parse_file=parse_file)


def test_ingest_explicit_office_file_missing_extra(monkeypatch, tmp_path):
    _office_error_parsers(monkeypatch)
    src = tmp_path / "notes.docx"
    src.write_bytes(b"PK fake docx")
    result = runner.invoke(
        app, ["ingest", str(tmp_path / "bundle"), str(src), "--no-llm"]
    )
    assert result.exit_code == 1
    assert "error [missing-extra]" in result.output
    assert "pip install" in result.output  # the install hint
    assert str(src) in result.output  # the file is named
    _no_traceback(result)


def test_ingest_directory_office_file_warns_and_skips(monkeypatch, tmp_path):
    # Directory-discovered files keep the graceful warn-and-skip behavior.
    _office_error_parsers(monkeypatch)
    srcdir = tmp_path / "src"
    srcdir.mkdir()
    (srcdir / "notes.docx").write_bytes(b"PK fake docx")
    result = runner.invoke(
        app, ["ingest", str(tmp_path / "bundle"), str(srcdir), "--no-llm"],
        env=WIDE,
    )
    assert result.exit_code == 0, result.output
    assert "skipped" in result.output
    assert "markitdown is not installed" in result.output


# ---------------------------------------------------------------------------
# L1 — pluralized counts in graph text output
# ---------------------------------------------------------------------------


def test_graph_text_pluralizes_counts():
    result = runner.invoke(
        app, ["graph", str(FIXTURES / "warn-dead-link")], env=WIDE
    )
    assert result.exit_code == 0, result.output
    assert "dead link(s)" not in result.output
    assert "concept(s)" not in result.output
    assert "1 dead link." in result.output


# ---------------------------------------------------------------------------
# L24 — unwritable bundle dir -> clean CliError
# ---------------------------------------------------------------------------


def test_ingest_unwritable_bundle_dir_clean_error(monkeypatch, tmp_path):
    _stub_parsers(monkeypatch)
    from okfsmith.core import indexlog

    def boom(bundle, **kwargs):
        raise PermissionError(13, "Permission denied", str(bundle.root))

    monkeypatch.setattr(indexlog, "append_log", boom)
    src = tmp_path / "doc.txt"
    src.write_text("hello", encoding="utf-8")
    result = runner.invoke(
        app, ["ingest", str(tmp_path / "bundle"), str(src), "--no-llm"]
    )
    assert result.exit_code == 1
    assert "error [io-error]" in result.output
    assert "hint:" in result.output
    _no_traceback(result)


# ---------------------------------------------------------------------------
# L25 — validate JSON standardizes on "count"
# ---------------------------------------------------------------------------


def test_validate_json_has_count_key(monkeypatch, tmp_path):
    _stub_validate(monkeypatch)
    bundle = _make_bundle(tmp_path)
    result = runner.invoke(
        app, ["validate", str(bundle), "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert isinstance(payload["count"], int)
    assert payload["count"] == payload["concepts"]  # back-compat alias


# ---------------------------------------------------------------------------
# M17 — the loaded Bundle is threaded through check()
# ---------------------------------------------------------------------------


def test_validate_passes_loaded_bundle_to_check(monkeypatch, tmp_path):
    """When check() supports the ``bundle`` keyword, it receives the bundle."""
    module = types.ModuleType("okfsmith.validate")
    seen: dict = {}

    def check(bundle_path, *, bundle=None):
        seen["path"] = bundle_path
        seen["bundle"] = bundle
        return ValidationReport(errors=[], warnings=[])

    module.check = check
    monkeypatch.setitem(sys.modules, "okfsmith.validate", module)
    bundle = _make_bundle(tmp_path)
    result = runner.invoke(app, ["validate", str(bundle)])
    assert result.exit_code == 0, result.output
    assert isinstance(seen["bundle"], Bundle)
    assert seen["bundle"].root == bundle.resolve()


def test_validate_old_check_signature_still_works(monkeypatch, tmp_path):
    """check() without the ``bundle`` keyword keeps working (path only)."""
    _stub_validate(monkeypatch)  # single-arg check(bundle_path)
    bundle = _make_bundle(tmp_path)
    result = runner.invoke(app, ["validate", str(bundle)])
    assert result.exit_code == 0, result.output
    assert "Conformant" in result.output


# ---------------------------------------------------------------------------
# C8 — BundleError -> error [io-error] in read/list/validate/graph/search/chat
# ---------------------------------------------------------------------------


@pytest.fixture()
def unreadable_bundle(monkeypatch, tmp_path):
    """Bundle.load raises BundleError naming notes.md, like non-UTF-8 input."""
    bundle = _make_bundle(tmp_path)

    def boom(root):
        raise _commands.BundleError(
            "notes.md: 'utf-8' codec can't decode byte 0xff"
        )

    monkeypatch.setattr(Bundle, "load", classmethod(lambda cls, root: boom(root)))
    return bundle


@pytest.mark.parametrize(
    "args",
    [
        ["list", "{b}"],
        ["read", "{b}", "some-id"],
        ["validate", "{b}"],
        ["graph", "{b}"],
    ],
)
def test_unreadable_bundle_file_clean_error(monkeypatch, unreadable_bundle, args):
    argv = [a.format(b=str(unreadable_bundle)) for a in args]
    result = runner.invoke(app, argv)
    assert result.exit_code == 1, result.output
    assert "error [io-error]" in result.output
    assert "notes.md" in result.output  # the file is named
    assert "hint:" in result.output
    _no_traceback(result)


def test_search_unreadable_bundle_file_clean_error(monkeypatch, unreadable_bundle):
    _stub_search(monkeypatch, [])
    result = runner.invoke(
        app, ["search", str(unreadable_bundle), "notes"]
    )
    assert result.exit_code == 1, result.output
    assert "error [io-error]" in result.output
    assert "notes.md" in result.output
    _no_traceback(result)


def test_chat_unreadable_bundle_file_clean_error(monkeypatch, unreadable_bundle):
    from okfsmith.cli import chat as chat_engine

    def boom(*args, **kwargs):
        raise _commands.BundleError(
            "notes.md: 'utf-8' codec can't decode byte 0xff"
        )

    monkeypatch.setattr(chat_engine, "run_chat", boom)
    result = runner.invoke(
        app, ["chat", str(unreadable_bundle), "--no-llm"], input="/exit\n"
    )
    assert result.exit_code == 1, result.output
    assert "error [io-error]" in result.output
    assert "notes.md" in result.output
    _no_traceback(result)
