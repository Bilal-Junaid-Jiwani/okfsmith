"""Typer commands for okfsmith.

This module only wires user input to business logic: the real work lives in
``okfsmith.core`` and the sibling slices (``parsers``, ``extract``,
``validate``, ``viz``, ``mcp_server``), which are imported lazily so each
command fails cleanly when its slice is not installed.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from okfsmith import links as _links
from okfsmith.cli.app import app
from okfsmith.core import Bundle, indexlog
from okfsmith.core import frontmatter as _fm
from okfsmith.core import spec as _spec

console = Console()


def _lazy_attr(module_name: str, attr: str) -> Any:
    """Import *attr* from *module_name*, failing cleanly if the slice is absent.

    Sibling slices (``okfsmith.parsers``, ``okfsmith.extract``,
    ``okfsmith.validate``, ``okfsmith.viz``, ``okfsmith.mcp_server``) are
    imported lazily; when one is not installed the command exits 1 with a
    clear message instead of an ImportError traceback. *module_name* may be a
    dotted submodule path (e.g. ``okfsmith.parsers.ingest_no_llm``).
    """
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        missing = exc.name or ""
        # The slice itself (or one of its parents under okfsmith) is absent.
        if module_name == missing or module_name.startswith(missing + "."):
            typer.echo(
                f"error: '{module_name}' is not available in this installation.",
                err=True,
            )
            raise typer.Exit(code=1)
        raise
    try:
        return getattr(module, attr)
    except AttributeError:
        typer.echo(
            f"error: '{module_name}' does not provide '{attr}'.", err=True
        )
        raise typer.Exit(code=1)


def _require_dir(path: Path, what: str = "directory") -> None:
    if not path.is_dir():
        typer.echo(f"error: {what} '{path}' does not exist.", err=True)
        raise typer.Exit(code=1)


def _collect_inputs(source: Path, recursive: bool) -> list[Path]:
    if source.is_file():
        return [source]
    iterator = source.rglob("*") if recursive else source.iterdir()
    return sorted(p for p in iterator if p.is_file())


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@app.command()
def init(
    directory: Path = typer.Argument(
        ..., help="Directory to scaffold the bundle in."
    ),
    force: bool = typer.Option(
        False, "--force", help="Scaffold even if the directory exists and is non-empty."
    ),
) -> None:
    """Create a new, empty OKF bundle in DIRECTORY."""
    if directory.exists() and any(directory.iterdir()) and not force:
        typer.echo(
            f"error: '{directory}' exists and is not empty "
            "(use --force to scaffold anyway).",
            err=True,
        )
        raise typer.Exit(code=1)
    directory.mkdir(parents=True, exist_ok=True)
    bundle = Bundle(directory)
    index_path = indexlog.ensure_index(bundle)
    log_path = indexlog.append_log(
        bundle, kind="Creation", message="Bundle created with `okfsmith init`."
    )
    typer.echo(f"Initialized OKF bundle in {directory}")
    typer.echo(f"  index: {index_path}")
    typer.echo(f"  log:   {log_path}")


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------


def _ingest_no_llm_one(
    path: Path,
    target: Bundle,
    *,
    parse_file: Any,
    ingest_no_llm: Any,
    sha256_of: Any,
    already_ingested: Any,
    record_ingested: Any,
) -> tuple[str, int]:
    """Ingest one file via deterministic sectioning. Returns (status, count)."""
    digest = sha256_of(path)
    if already_ingested(target, digest):
        return "skipped (already ingested)", 0
    parsed = parse_file(path)
    created = ingest_no_llm(target, parsed, str(path))
    record_ingested(target, digest, str(path))
    return "ok", len(created)


def _ingest_llm_one(
    path: Path,
    target: Bundle,
    *,
    parse_file: Any,
    section: Any,
    SectionInput: Any,
    run: Any,
    model: str | None,
) -> tuple[str, int]:
    """Ingest one file via the LLM extraction pipeline. Returns (status, count)."""
    parsed = parse_file(path)
    sectioned = section(parsed)
    doc_title = (parsed.meta or {}).get("title") or path.stem
    sections = [
        SectionInput(
            title=sec.title,
            level=sec.level,
            text=sec.text,
            page_span=sec.page_span,
            tables=list(sec.tables or []),
            source_id=str(path),
            source_path=str(path),
            doc_title=doc_title,
        )
        for sec in sectioned.sections
    ]
    created = run(target, sections, model=model)
    return "ok", len(created)


@app.command()
def ingest(
    source: Path = typer.Argument(..., help="File or directory to ingest."),
    bundle: Path = typer.Option(..., "--bundle", help="Target bundle directory."),
    model: str | None = typer.Option(
        None, "--model", help="Model to use for LLM extraction."
    ),
    no_llm: bool = typer.Option(
        False,
        "--no-llm",
        help="Use deterministic sectioning (okfsmith.parsers) instead of an LLM.",
    ),
    recursive: bool = typer.Option(
        False,
        "--recursive",
        help="Recurse into subdirectories when SOURCE is a directory.",
    ),
) -> None:
    """Ingest documents into the bundle as draft concepts.

    With ``--no-llm`` the deterministic sectioning path is used
    (``okfsmith.parsers.ingest_no_llm``) with per-file SHA-256 dedup via the
    bundle manifest; otherwise the LLM extraction path
    (``okfsmith.extract.run``) is used.
    """
    if not source.exists():
        typer.echo(f"error: source '{source}' does not exist.", err=True)
        raise typer.Exit(code=1)
    files = _collect_inputs(source, recursive)
    if not files:
        typer.echo(f"error: no input files found under '{source}'.", err=True)
        raise typer.Exit(code=1)

    parse_file = _lazy_attr("okfsmith.parsers", "parse_file")
    if no_llm:
        ingest_no_llm = _lazy_attr(
            "okfsmith.parsers.ingest_no_llm", "ingest_no_llm"
        )
        sha256_of = _lazy_attr("okfsmith.parsers.dedup", "sha256_of")
        already_ingested = _lazy_attr("okfsmith.parsers.dedup", "already_ingested")
        record_ingested = _lazy_attr("okfsmith.parsers.dedup", "record_ingested")
        mode = "sectioning (no LLM)"
    else:
        section = _lazy_attr("okfsmith.parsers.sectioning", "section")
        SectionInput = _lazy_attr("okfsmith.extract", "SectionInput")
        run = _lazy_attr("okfsmith.extract", "run")
        LLMUnavailableError = _lazy_attr("okfsmith.extract", "LLMUnavailableError")
        mode = f"LLM extraction (model={model or 'default'})"

    target = Bundle.load(bundle)
    table = Table(title=f"Ingest summary — {mode}")
    table.add_column("File")
    table.add_column("SHA-256")
    table.add_column("Concepts", justify="right")
    table.add_column("Status")

    digest_of = _lazy_attr("okfsmith.parsers.dedup", "sha256_of")
    failures: list[Path] = []
    created_total = 0
    for path in files:
        digest = digest_of(path)[:12]
        try:
            if no_llm:
                status, count = _ingest_no_llm_one(
                    path,
                    target,
                    parse_file=parse_file,
                    ingest_no_llm=ingest_no_llm,
                    sha256_of=digest_of,
                    already_ingested=already_ingested,
                    record_ingested=record_ingested,
                )
                style = "green" if status == "ok" else "yellow"
                table.add_row(str(path), digest, str(count), f"[{style}]{status}[/{style}]")
            else:
                try:
                    status, count = _ingest_llm_one(
                        path,
                        target,
                        parse_file=parse_file,
                        section=section,
                        SectionInput=SectionInput,
                        run=run,
                        model=model,
                    )
                except LLMUnavailableError as exc:
                    typer.echo(f"error: LLM unavailable: {exc}", err=True)
                    raise typer.Exit(code=1)
                table.add_row(str(path), digest, str(count), "[green]ok[/green]")
            created_total += count
        except typer.Exit:
            raise
        except Exception as exc:  # noqa: BLE001 — per-file failure, keep going
            failures.append(path)
            table.add_row(str(path), digest, "0", f"[red]failed: {exc}[/red]")
    console.print(table)

    if created_total:
        indexlog.ensure_index(target)
        indexlog.append_log(
            target,
            kind="Update",
            message=(
                f"Ingested {created_total} draft concept(s) from "
                f"{len(files) - len(failures)} source file(s)."
            ),
        )
        typer.echo(f"Wrote {created_total} draft concept(s) to {bundle}")
    if failures and len(failures) == len(files):
        typer.echo("error: all inputs failed to ingest.", err=True)
        raise typer.Exit(code=1)
    if failures:
        typer.echo(
            f"warning: {len(failures)} of {len(files)} input(s) failed.", err=True
        )


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


@app.command()
def validate(
    directory: Path = typer.Argument(..., help="Bundle directory to validate."),
    strict: bool = typer.Option(
        False, "--strict", help="Treat warnings as failures."
    ),
    output_format: str = typer.Option(
        "text", "--format", help="Output format: text or json."
    ),
) -> None:
    """Validate a bundle against OKF v0.2 (E001–E004 / W001–W015)."""
    _require_dir(directory)
    # check(bundle_path) -> ValidationReport with .errors / .warnings as
    # Finding objects; serialize each via Finding.as_dict().
    check = _lazy_attr("okfsmith.validate", "check")
    result = check(directory)
    errors = [finding.as_dict() for finding in result.errors]
    warnings = [finding.as_dict() for finding in result.warnings]

    if output_format == "json":
        typer.echo(json.dumps({"errors": errors, "warnings": warnings}, indent=2))
    elif output_format == "text":
        _print_report(errors, warnings)
    else:
        typer.echo(f"error: unknown --format '{output_format}' (use text or json).", err=True)
        raise typer.Exit(code=1)

    if errors or (strict and warnings):
        raise typer.Exit(code=1)


def _print_report(errors: list[dict], warnings: list[dict]) -> None:
    for title, items, style in (
        ("Errors", errors, "red"),
        ("Warnings", warnings, "yellow"),
    ):
        table = Table(title=f"{title} ({len(items)})")
        table.add_column("Code", style=style)
        table.add_column("File")
        table.add_column("Message")
        for item in items:
            table.add_row(
                str(item.get("code", "")),
                str(item.get("file", "")),
                str(item.get("message", "")),
            )
        console.print(table)
    if errors:
        typer.echo(f"INVALID: {len(errors)} error(s), {len(warnings)} warning(s).")
    elif warnings:
        typer.echo(f"Conformant with {len(warnings)} warning(s).")
    else:
        typer.echo("Conformant: no errors, no warnings.")


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@app.command(name="list")
def list_concepts(
    directory: Path = typer.Argument(..., help="Bundle directory to list."),
    type_filter: str | None = typer.Option(
        None, "--type", help="Only show concepts of this type."
    ),
    tier_filter: str | None = typer.Option(
        None, "--tier", help="Only show concepts with this trust tier."
    ),
) -> None:
    """List concepts in the bundle: id, type, title, trust tier."""
    _require_dir(directory)
    bundle = Bundle.load(directory)
    table = Table(title=f"Concepts in {directory}")
    table.add_column("ID")
    table.add_column("Type")
    table.add_column("Title")
    table.add_column("Trust tier")
    shown = 0
    for concept in bundle.iter_concepts():
        ctype = str(concept.frontmatter.get("type") or "")
        tier = _spec.trust_tier(concept.frontmatter)
        if type_filter and ctype.casefold() != type_filter.casefold():
            continue
        if tier_filter and tier.casefold() != tier_filter.casefold():
            continue
        table.add_row(
            concept.id, ctype, str(concept.frontmatter.get("title") or ""), tier
        )
        shown += 1
    console.print(table)
    typer.echo(f"{shown} concept(s)")


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


@app.command()
def read(
    directory: Path = typer.Argument(..., help="Bundle directory."),
    concept_id: str = typer.Argument(..., help="Concept id, e.g. finance/revenue."),
) -> None:
    """Print a concept: frontmatter as YAML, then the body."""
    _require_dir(directory)
    bundle = Bundle.load(directory)
    concept = bundle.get(concept_id)
    if concept is None:
        typer.echo(
            f"error: concept '{concept_id}' not found in '{directory}'.", err=True
        )
        raise typer.Exit(code=1)
    typer.echo(_fm.serialize_frontmatter(concept.frontmatter, concept.body))


# ---------------------------------------------------------------------------
# graph
# ---------------------------------------------------------------------------


@app.command()
def graph(
    directory: Path = typer.Argument(..., help="Bundle directory."),
    output_format: str = typer.Option(
        "text", "--format", help="Output format: text, json, mermaid, or html."
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        help="Output file for --format html (default: <bundle>/viz.html).",
    ),
) -> None:
    """Show the concept link graph (nodes, edges, orphans, dead links)."""
    _require_dir(directory)
    bundle = Bundle.load(directory)
    data = _links.build_graph(bundle)

    if output_format == "json":
        adjacency: dict[str, list[str]] = {}
        for node in data["nodes"]:
            adjacency[node["id"]] = []
        for edge in data["edges"]:
            adjacency.setdefault(edge["from"], []).append(edge["to"])
        typer.echo(
            json.dumps({"nodes": data["nodes"], "adjacency": adjacency}, indent=2)
        )
    elif output_format == "mermaid":
        typer.echo(_links.mermaid_flowchart(data), nl=False)
    elif output_format == "html":
        # render_html(root, output) -> Path
        render_html = _lazy_attr("okfsmith.viz", "render_html")
        out_path = output or (Path(directory) / "viz.html")
        written = render_html(Path(directory), out_path)
        typer.echo(f"Wrote {written}")
    elif output_format == "text":
        _print_graph_text(bundle, data)
    else:
        typer.echo(
            f"error: unknown --format '{output_format}' "
            "(use text, json, mermaid, or html).",
            err=True,
        )
        raise typer.Exit(code=1)


def _print_graph_text(bundle: Bundle, data: dict) -> None:
    typer.echo(
        f"{len(data['nodes'])} concept(s), {len(data['edges'])} link(s), "
        f"{len(data['dead_links'])} dead link(s)."
    )
    orphan_ids = _links.orphans(bundle)
    typer.echo(f"\nOrphans ({len(orphan_ids)}):")
    for oid in orphan_ids:
        typer.echo(f"  - {oid}")
    if not orphan_ids:
        typer.echo("  (none)")
    typer.echo(f"\nDead links ({len(data['dead_links'])}):")
    for item in data["dead_links"]:
        typer.echo(f"  - {item['source']}: {item['target']}")
    if not data["dead_links"]:
        typer.echo("  (none)")


# ---------------------------------------------------------------------------
# mcp
# ---------------------------------------------------------------------------


@app.command()
def mcp(
    bundle: Path = typer.Option(..., "--bundle", help="Bundle directory to serve."),
    transport: str = typer.Option(
        "stdio", "--transport", help="MCP transport to use."
    ),
) -> None:
    """Serve the bundle over MCP (Model Context Protocol)."""
    _require_dir(bundle, "bundle")
    # serve(bundle_path, transport) -> None
    serve = _lazy_attr("okfsmith.mcp_server", "serve")
    serve(bundle, transport)
