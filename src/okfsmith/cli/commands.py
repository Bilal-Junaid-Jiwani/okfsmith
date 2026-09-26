"""Typer commands for okfsmith.

This module only wires user input to business logic: the real work lives in
``okfsmith.core`` and the sibling slices (``parsers``, ``extract``,
``validate``, ``viz``, ``mcp_server``), which are imported lazily so each
command fails cleanly when its slice is not installed.

Conventions (UX panels A/B, review-gate items 2/4/5/7/8):

- the bundle is always the **first positional** argument;
- ``--format`` / ``--transport`` values are constrained choices: an invalid
  value is a usage error (exit 2), not a runtime error;
- all paths and flags are validated *before* any lazy import runs;
- expected failures print ``error [CODE]: message`` plus a ``hint:`` line on
  stderr and exit non-zero — never a traceback. ``CODE`` is a stable,
  machine-readable error code (``--format json`` commands emit the same
  failure as JSON on stdout);
- destructive ``init --force`` asks for confirmation unless ``--yes``.
"""

from __future__ import annotations

import functools
import importlib
import json
import sys
from enum import Enum
from pathlib import Path
from typing import Any, NoReturn

import typer
from rich.console import Console
from rich.markup import escape
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from okfsmith import links as _links
from okfsmith.cli.app import app
from okfsmith.core import Bundle, indexlog
from okfsmith.core import frontmatter as _fm
from okfsmith.core import spec as _spec

console = Console()

PANEL_BUNDLE = "Bundle"
PANEL_KNOWLEDGE = "Knowledge"
PANEL_SERVE = "Serve"

class ValidateFormat(str, Enum):
    """Constrained ``--format`` values for validate/list/read (exit 2 on misuse)."""
    text = "text"
    json = "json"


class GraphFormat(str, Enum):
    """Constrained ``--format`` values for graph (exit 2 on misuse)."""
    text = "text"
    json = "json"
    mermaid = "mermaid"
    html = "html"


class McpTransport(str, Enum):
    """Constrained ``--transport`` values for mcp (exit 2 on misuse)."""
    stdio = "stdio"
    sse = "sse"
    streamable_http = "streamable-http"

TRUST_TIERS = ("unverified", "machine-confirmed", "human-reviewed")


class CliError(Exception):
    """An expected, user-facing failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


def fail(
    code: str, message: str, hint: str | None = None, *, exit_code: int = 1
) -> NoReturn:
    """Print ``error [CODE]: message`` (+ optional hint) and exit."""
    typer.echo(f"error [{code}]: {message}", err=True)
    if hint:
        typer.echo(f"hint: {hint}", err=True)
    raise typer.Exit(code=exit_code)


def _fail_json(code: str, message: str, hint: str | None = None) -> NoReturn:
    """Emit a machine-readable error object on stdout and exit 1."""
    payload: dict[str, Any] = {"status": "error", "code": code, "message": message}
    if hint:
        payload["hint"] = hint
    typer.echo(json.dumps(payload, indent=2))
    raise typer.Exit(code=1)


def _jsonable(value: Any) -> Any:
    """Make frontmatter values JSON-serializable (datetimes -> ISO 8601)."""
    import datetime

    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_jsonable(v) for v in value), key=repr)
    return value


def _dump_json(payload: Any) -> None:
    typer.echo(json.dumps(_jsonable(payload), indent=2))


def _handle_cli_error(exc: CliError, as_json: bool) -> NoReturn:
    if as_json:
        _fail_json(exc.code, exc.message, exc.hint)
    fail(exc.code, exc.message, exc.hint)
    raise AssertionError("unreachable")  # pragma: no cover


def _cli(fn):
    """Command decorator: turn CliError into a clean stderr message (exit 1).

    Commands raising ``fail()``-style errors already exit directly; this
    catches the remaining structured errors (missing slices, bad bundle
    shape, LLM outages) so users never see a traceback. JSON-output commands
    get a JSON error object when ``--format json`` was requested.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        fmt = kwargs.get("output_format")
        try:
            return fn(*args, **kwargs)
        except CliError as exc:
            _handle_cli_error(exc, as_json=(fmt == "json"))

    return wrapper


def _install_extra_hint(extra: str) -> str:
    """Install guidance for an optional extra across pip / pipx / uvx."""
    return (
        f"Install the '{extra}' extra: pip install 'okfsmith[{extra}]' "
        f"(pipx: pipx install 'okfsmith[{extra}]'; "
        f"uvx: uvx --with 'okfsmith[{extra}]')."
    )


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
            raise CliError(
                "slice-not-installed",
                f"'{module_name}' is not available in this installation.",
                _install_extra_hint(_extra_for(module_name)),
            ) from None
        raise
    try:
        return getattr(module, attr)
    except AttributeError:
        raise CliError(
            "slice-incomplete",
            f"'{module_name}' does not provide '{attr}'.",
            "Reinstall okfsmith; if the problem persists, file a bug report.",
        ) from None


def _extra_for(module_name: str) -> str:
    if module_name.startswith("okfsmith.mcp_server"):
        return "mcp"
    if module_name.startswith("okfsmith.parsers.office"):
        return "office"
    return "test"


def _looks_like_bundle(path: Path) -> bool:
    """True when *path* contains any bundle signal (concepts or reserved files)."""
    if (path / "index.md").is_file() or (path / "log.md").is_file():
        return True
    return any(path.rglob("*.md"))


def _require_bundle_dir(path: Path) -> Path:
    """Validate *path* as an existing bundle directory (read commands).

    Raises :class:`CliError` distinguishing a missing path, a non-directory,
    and an existing directory that is not a bundle.
    """
    if not path.exists():
        raise CliError(
            "bundle-not-found",
            f"bundle '{path}' does not exist.",
            f"Run 'okfsmith init {path}' to create one.",
        )
    if not path.is_dir():
        raise CliError(
            "not-a-directory",
            f"'{path}' exists but is not a directory.",
            "Pass the bundle directory, not a file inside it.",
        )
    if not _looks_like_bundle(path):
        raise CliError(
            "not-a-bundle",
            f"'{path}' does not look like an OKF bundle (no markdown files).",
            f"Run 'okfsmith init {path}' to create one, or pass an existing bundle.",
        )
    return path


_RESERVED_NAMES = frozenset({"index.md", "log.md"})


def _collect_inputs(source: Path, recursive: bool) -> list[Path]:
    if source.is_file():
        return [source]
    iterator = source.rglob("*") if recursive else source.iterdir()
    # Reserved bundle files are infrastructure, never knowledge sources.
    return sorted(
        p for p in iterator if p.is_file() and p.name not in _RESERVED_NAMES
    )


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@app.command(rich_help_panel=PANEL_BUNDLE)
@_cli
def init(
    bundle: Path = typer.Argument(
        ..., help="Directory to scaffold the bundle in."
    ),
    force: bool = typer.Option(
        False, "--force", help="Scaffold even if the bundle exists and is non-empty."
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Answer 'yes' to the --force confirmation prompt (non-interactive use).",
    ),
) -> None:
    """Create a new, empty OKF bundle in BUNDLE.

    \b
    Examples:
        okfsmith init ./kb
        okfsmith init ./kb --force --yes   # non-interactive re-scaffold
    """
    if bundle.exists() and not bundle.is_dir():
        fail(
            "not-a-directory",
            f"'{bundle}' exists but is not a directory.",
            "Pick a directory path for the bundle (or remove the file).",
        )
    if bundle.exists() and any(bundle.iterdir()) and not force:
        fail(
            "bundle-not-empty",
            f"'{bundle}' exists and is not empty.",
            "Use --force to scaffold anyway (asks for confirmation), or pick another bundle.",
        )
    if bundle.exists() and any(bundle.iterdir()) and force and not yes:
        typer.echo(
            f"warning: '{bundle}' is not empty; --force will scaffold over it.",
            err=True,
        )
        if not typer.confirm("Continue?", default=False):
            typer.echo("aborted.", err=True)
            raise typer.Exit(code=1)
    bundle.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle
    bundle = Bundle(bundle_path)
    index_path = indexlog.ensure_index(bundle)
    log_path = indexlog.append_log(
        bundle, kind="Creation", message="Bundle created with `okfsmith init`."
    )
    typer.echo(f"Initialized OKF bundle in {bundle_path}")
    typer.echo(f"  index: {index_path}")
    typer.echo(f"  log:   {log_path}")
    typer.echo("Next: add sources with 'okfsmith ingest "
               f"{bundle_path} <file-or-dir> --no-llm'.")


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
    sectioning: Any,
) -> tuple[str, int]:
    """Ingest one file via deterministic sectioning. Returns (status, count)."""
    digest = sha256_of(path)
    if already_ingested(target, digest):
        return "skipped (already ingested)", 0
    parsed = parse_file(path)
    # Stub prevention: sources under the char minimum produce no concepts.
    # Say so explicitly instead of reporting a hollow "ok", and do not record
    # the digest — the file was not ingested, so a later retry must surface
    # the same reason instead of claiming "already ingested".
    if sectioning.section(parsed).too_small:
        return (
            f"skipped (below {sectioning.TOO_SMALL_CHARS}-char minimum; "
            "stub prevention)",
            0,
        )
    created = ingest_no_llm(target, parsed, str(path))
    if not created:
        return "skipped (no concepts created)", 0
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


@app.command(rich_help_panel=PANEL_KNOWLEDGE)
@_cli
def ingest(
    bundle: Path = typer.Argument(
        ..., help="Bundle directory to ingest into (created if missing)."
    ),
    sources: list[Path] = typer.Argument(
        ..., help="File(s) or directories to ingest."
    ),
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
        help="Recurse into subdirectories when a SOURCE is a directory.",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Only print warnings, errors, and the final summary line.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Parse and plan only; write nothing to the bundle.",
    ),
) -> None:
    """Ingest documents into BUNDLE as draft concepts.

    With ``--no-llm`` the deterministic sectioning path is used
    (``okfsmith.parsers.ingest_no_llm``) with per-file SHA-256 dedup via the
    bundle manifest; otherwise the LLM extraction path
    (``okfsmith.extract.run``) is used.

    \b
    Examples:
        okfsmith ingest ./kb docs/report.pdf --no-llm
        okfsmith ingest ./kb docs/ --recursive --no-llm
        okfsmith ingest ./kb paper.pdf --dry-run
        okfsmith ingest ./kb paper.pdf --quiet
    """
    # --- validate everything before any lazy import (review-gate item 4) ---
    if model is not None and no_llm:
        raise typer.BadParameter(
            "--model cannot be combined with --no-llm: no LLM is used in that mode."
        )
    files: list[Path] = []
    for source in sources:
        if not source.exists():
            fail(
                "source-not-found",
                f"source '{source}' does not exist.",
                "Pass an existing file or directory.",
            )
        found = _collect_inputs(source, recursive)
        if not found:
            fail(
                "no-input-files",
                f"no input files found under '{source}'.",
                "Pass a file, or add --recursive for directories.",
            )
        files.extend(found)

    parse_file = _lazy_attr("okfsmith.parsers", "parse_file")
    if no_llm:
        ingest_no_llm = _lazy_attr("okfsmith.parsers.ingest_no_llm", "ingest_no_llm")
        already_ingested = _lazy_attr("okfsmith.parsers.dedup", "already_ingested")
        record_ingested = _lazy_attr("okfsmith.parsers.dedup", "record_ingested")
        # The parsers slice is definitely present here (parse_file imported
        # above), so import the module directly for section()/TOO_SMALL_CHARS.
        sectioning = importlib.import_module("okfsmith.parsers.sectioning")
        mode = "sectioning (no LLM)"
    else:
        section = _lazy_attr("okfsmith.parsers.sectioning", "section")
        SectionInput = _lazy_attr("okfsmith.extract", "SectionInput")
        run = _lazy_attr("okfsmith.extract", "run")
        LLMUnavailableError = _lazy_attr("okfsmith.extract", "LLMUnavailableError")
        mode = f"LLM extraction (model={model or 'default'})"

    if dry_run:
        _ingest_dry_run(bundle, files, no_llm=no_llm, parse_file=parse_file,
                        section=section if not no_llm else None, quiet=quiet)
        return

    target = Bundle.load(bundle)
    digest_of = _lazy_attr("okfsmith.parsers.dedup", "sha256_of")
    failures: list[Path] = []
    created_total = 0
    rows: list[tuple[str, str, str, str]] = []

    show_progress = not quiet and sys.stderr.isatty()
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        disable=not show_progress,
    )
    with progress:
        task = progress.add_task(f"ingesting {len(files)} file(s) — {mode}", total=len(files))
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
                        sectioning=sectioning,
                    )
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
                        raise CliError(
                            "llm-unavailable",
                            f"LLM unavailable: {exc}",
                            "Start Ollama ('ollama serve'), set OKFSMITH_MODEL / "
                            "OPENAI_API_KEY, or retry with --no-llm.",
                        ) from None
                created_total += count
                rows.append((str(path), digest, str(count), status))
            except CliError:
                raise
            except typer.Exit:
                raise
            except Exception as exc:  # noqa: BLE001 — per-file failure, keep going
                failures.append(path)
                # Security (audit-3 finding 4): escape untrusted exception text.
                rows.append((str(path), digest, "0", f"failed: {escape(str(exc))}"))
            progress.advance(task)

    if not quiet:
        table = Table(title=f"Ingest summary — {mode}")
        table.add_column("File")
        table.add_column("SHA-256")
        table.add_column("Concepts", justify="right")
        table.add_column("Status")
        for file, digest, count, status in rows:
            if status == "ok":
                style = "green"
            elif status.startswith("skipped"):
                style = "yellow"
            else:
                style = "red"
            table.add_row(escape(file), digest, count, f"[{style}]{escape(status)}[/{style}]")
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
    summary = (
        f"ingested {created_total} concept(s) from {len(files)} file(s)"
        + (f", {len(failures)} failed" if failures else "")
        + f" into {bundle}"
    )
    typer.echo(summary)
    if failures and len(failures) == len(files):
        fail("ingest-failed", "all inputs failed to ingest.",
             "Run with --dry-run to inspect parsing without writing.")
    if failures:
        typer.echo(
            f"warning: {len(failures)} of {len(files)} input(s) failed.", err=True
        )


def _ingest_dry_run(
    bundle: Path,
    files: list[Path],
    *,
    no_llm: bool,
    parse_file: Any,
    section: Any,
    quiet: bool,
) -> None:
    """Parse and plan an ingest without writing anything."""
    typer.echo(f"dry run: would ingest {len(files)} file(s) into {bundle} (nothing written)")
    section_fn = section
    too_small_chars = None
    if no_llm:
        sectioning = importlib.import_module("okfsmith.parsers.sectioning")
        section_fn = sectioning.section
        too_small_chars = sectioning.TOO_SMALL_CHARS
    for path in files:
        try:
            parsed = parse_file(path)
        except Exception as exc:  # noqa: BLE001 — dry run reports, never raises
            typer.echo(f"  {path}: would skip ({escape(str(exc))})")
            continue
        if (parsed.meta or {}).get("error"):
            typer.echo(f"  {path}: would skip ({escape(str(parsed.meta['error']))})")
            continue
        pages = len(parsed.pages or [])
        try:
            sectioned = section_fn(parsed)
        except Exception:  # noqa: BLE001
            sectioned = None
        if sectioned is None:
            typer.echo(f"  {path}: would skip (sectioning failed)")
            continue
        # Parity with the real ingest: the stub-prevention threshold applies
        # here too, so dry-run never predicts concepts that won't be created.
        if too_small_chars is not None and sectioned.too_small:
            typer.echo(
                f"  {path}: would skip (below {too_small_chars}-char minimum; "
                "stub prevention)"
            )
            continue
        n_sections = len(sectioned.sections)
        typer.echo(
            f"  {path}: {pages} page(s), ~{n_sections} section(s) → draft concepts"
        )


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


@app.command(rich_help_panel=PANEL_KNOWLEDGE)
@_cli
def validate(
    bundle: Path = typer.Argument(..., help="Bundle directory to validate."),
    strict: bool = typer.Option(
        False, "--strict", help="Treat warnings as failures."
    ),
    output_format: ValidateFormat = typer.Option(
        ValidateFormat.text, "--format", help="Output format: text or json."
    ),
) -> None:
    """Validate a bundle against OKF v0.2 (E001–E004 / W001–W015).

    \b
    Examples:
        okfsmith validate ./kb
        okfsmith validate ./kb --format json
        okfsmith validate ./kb --strict
    """
    as_json = output_format == "json"
    try:
        _require_bundle_dir(bundle)
    except CliError as exc:
        _handle_cli_error(exc, as_json)
    # check(bundle_path) -> ValidationReport with .errors / .warnings as
    # Finding objects; serialize each via Finding.as_dict().
    check = _lazy_attr("okfsmith.validate", "check")
    result = check(bundle)
    errors = [finding.as_dict() for finding in result.errors]
    warnings = [finding.as_dict() for finding in result.warnings]
    n_concepts = sum(1 for _ in Bundle.load(bundle).iter_concepts())

    if as_json:
        status = "invalid" if errors or (strict and warnings) else "conformant"
        _dump_json({
            "status": status,
            "concepts": n_concepts,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "errors": errors,
            "warnings": warnings,
        })
    else:
        _print_report(errors, warnings)

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
                escape(str(item.get("code", ""))),
                escape(str(item.get("file", ""))),
                escape(str(item.get("message", ""))),
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


@app.command(name="list", rich_help_panel=PANEL_KNOWLEDGE)
@_cli
def list_concepts(
    bundle: Path = typer.Argument(..., help="Bundle directory to list."),
    type_filter: str | None = typer.Option(
        None, "--type", help="Only show concepts of this type."
    ),
    tier_filter: str | None = typer.Option(
        None, "--tier",
        help=f"Only show concepts with this trust tier ({', '.join(TRUST_TIERS)}).",
    ),
    output_format: ValidateFormat = typer.Option(
        ValidateFormat.text, "--format", help="Output format: text or json."
    ),
) -> None:
    """List concepts in the bundle: id, type, title, trust tier.

    \b
    Examples:
        okfsmith list ./kb
        okfsmith list ./kb --tier human-reviewed --format json
    """
    as_json = output_format == "json"
    if tier_filter is not None and tier_filter.casefold() not in TRUST_TIERS:
        raise typer.BadParameter(
            f"--tier '{tier_filter}' is not one of: {', '.join(TRUST_TIERS)}"
        )
    try:
        _require_bundle_dir(bundle)
    except CliError as exc:
        _handle_cli_error(exc, as_json)
    bundle_path = bundle
    bundle = Bundle.load(bundle_path)
    rows = []
    for concept in bundle.iter_concepts():
        ctype = str(concept.frontmatter.get("type") or "")
        tier = _spec.trust_tier(concept.frontmatter)
        if type_filter and ctype.casefold() != type_filter.casefold():
            continue
        if tier_filter and tier.casefold() != tier_filter.casefold():
            continue
        rows.append({
            "id": concept.id,
            "type": ctype,
            "title": str(concept.frontmatter.get("title") or ""),
            "tier": tier,
        })
    if as_json:
        _dump_json({"concepts": rows, "count": len(rows)})
        return
    table = Table(title=f"Concepts in {bundle_path}")
    # IDs must never truncate: users copy-paste them into `read`.
    table.add_column("ID", no_wrap=True, overflow="fold")
    table.add_column("Type")
    table.add_column("Title")
    table.add_column("Trust tier")
    for row in rows:
        table.add_row(escape(row["id"]), escape(row["type"]), escape(row["title"]), escape(row["tier"]))
    console.print(table)
    typer.echo(f"{len(rows)} concept(s)")
    if not rows:
        typer.echo(
            f"hint: add sources with 'okfsmith ingest {bundle_path} <file-or-dir> --no-llm'.",
            err=True,
        )


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


@app.command(rich_help_panel=PANEL_KNOWLEDGE)
@_cli
def read(
    bundle: Path = typer.Argument(..., help="Bundle directory."),
    concept_id: str = typer.Argument(..., help="Concept id, e.g. finance/revenue."),
    output_format: ValidateFormat = typer.Option(
        ValidateFormat.text, "--format", help="Output format: text or json."
    ),
) -> None:
    """Print a concept: frontmatter as YAML, then the body.

    \b
    Examples:
        okfsmith read ./kb finance/revenue
        okfsmith read ./kb finance/revenue --format json
    """
    as_json = output_format == "json"
    try:
        _require_bundle_dir(bundle)
    except CliError as exc:
        _handle_cli_error(exc, as_json)
    bundle_path = bundle
    bundle = Bundle.load(bundle_path)
    concept = bundle.get(concept_id)
    if concept is None:
        if as_json:
            _fail_json(
                "concept-not-found",
                f"concept '{concept_id}' not found in '{bundle_path}'.",
                f"Run 'okfsmith list {bundle_path}' to see available ids.",
            )
        fail(
            "concept-not-found",
            f"concept '{concept_id}' not found in '{bundle_path}'.",
            f"Run 'okfsmith list {bundle_path}' to see available ids.",
        )
    assert concept is not None  # for type checkers; fail() raises
    if as_json:
        _dump_json({
            "id": concept.id,
            "frontmatter": concept.frontmatter,
            "body": concept.body,
        })
    else:
        typer.echo(_fm.serialize_frontmatter(concept.frontmatter, concept.body))


# ---------------------------------------------------------------------------
# graph
# ---------------------------------------------------------------------------


@app.command(rich_help_panel=PANEL_KNOWLEDGE)
@_cli
def graph(
    bundle: Path = typer.Argument(..., help="Bundle directory."),
    output_format: GraphFormat = typer.Option(
        GraphFormat.text, "--format",
        help="Output format: text, json, mermaid, or html.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        help="Write output to this file instead of stdout (default for html: <bundle>/viz.html).",
    ),
) -> None:
    """Show the concept link graph (nodes, edges, orphans, dead links).

    \b
    Examples:
        okfsmith graph ./kb
        okfsmith graph ./kb --format html --output graph.html
    """
    as_json = output_format == "json"
    try:
        _require_bundle_dir(bundle)
    except CliError as exc:
        _handle_cli_error(exc, as_json)
    if output_format == "html" and output is not None and output.exists() and not output.is_file():
        fail(
            "invalid-output",
            f"--output '{output}' is not a file path.",
            "Give a path to a file (it will be created), not a directory.",
        )
    bundle_path = bundle
    bundle = Bundle.load(bundle_path)
    data = _links.build_graph(bundle)

    if output_format == "json":
        adjacency: dict[str, list[str]] = {}
        for node in data["nodes"]:
            adjacency[node["id"]] = []
        for edge in data["edges"]:
            adjacency.setdefault(edge["from"], []).append(edge["to"])
        payload = {
            "nodes": data["nodes"],
            "adjacency": adjacency,
            "dead_links": data["dead_links"],
        }
        if output is not None:
            output.write_text(
                json.dumps(_jsonable(payload), indent=2), encoding="utf-8"
            )
            typer.echo(f"Wrote {output}")
        else:
            _dump_json(payload)
    elif output_format == "mermaid":
        text = _links.mermaid_flowchart(data)
        if output is not None:
            output.write_text(text, encoding="utf-8")
            typer.echo(f"Wrote {output}")
        else:
            typer.echo(text, nl=False)
    elif output_format == "html":
        # render_html(root, output) -> Path
        render_html = _lazy_attr("okfsmith.viz", "render_html")
        out_path = output or (bundle_path / "viz.html")
        written = render_html(bundle_path, out_path)
        typer.echo(f"Wrote {written}")
    elif output_format == "text":
        if output is not None:
            # Capture the text report and write it to the file.
            import io
            from contextlib import redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf):
                _print_graph_text(bundle, data)
            output.write_text(buf.getvalue(), encoding="utf-8")
            typer.echo(f"Wrote {output}")
        else:
            _print_graph_text(bundle, data)


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


@app.command(rich_help_panel=PANEL_SERVE)
@_cli
def mcp(
    bundle: Path = typer.Argument(..., help="Bundle directory to serve."),
    transport: McpTransport = typer.Option(
        McpTransport.stdio, "--transport", help="MCP transport to use."
    ),
) -> None:
    """Serve the bundle over MCP (Model Context Protocol).

    \b
    Examples:
        okfsmith mcp ./kb
        uvx --with "okfsmith[mcp]" okfsmith mcp ./kb
    """
    try:
        _require_bundle_dir(bundle)
    except CliError as exc:
        _handle_cli_error(exc, False)
    # serve(bundle_path, transport) -> None
    serve = _lazy_attr("okfsmith.mcp_server", "serve")
    try:
        serve(bundle, transport)
    except RuntimeError as exc:
        # Missing 'mcp' extra (fastmcp not installed): surface the stable
        # error/hint contract, never a traceback.
        fail(
            "missing-extra",
            str(exc),
            'Install it with: pip install "okfsmith[mcp]" '
            '(or pipx: pipx install "okfsmith[mcp]", '
            'or uvx: uvx --with "okfsmith[mcp]" okfsmith mcp ./kb)',
        )


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


@app.command(rich_help_panel=PANEL_BUNDLE)
@_cli
def doctor() -> None:
    """Check the environment: dependencies, extras, Ollama, writability.

    Reports OK / MISSING / WARN per check so a broken setup is diagnosable
    in one command.
    """
    import okfsmith

    rows: list[tuple[str, str, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        rows.append((name, "OK" if ok else "MISSING", detail))

    py_ok = sys.version_info >= (3, 10)
    rows.append(("python >= 3.10", "OK" if py_ok else "FAIL",
                 ".".join(map(str, sys.version_info[:3]))))
    check("okfsmith", True, okfsmith.__version__)
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _pkg_version

    def _mod_version(mod, dist: str) -> str:
        v = getattr(mod, "__version__", None)
        if v:
            return str(v)
        try:
            return _pkg_version(dist)
        except PackageNotFoundError:
            return "?"

    for mod, label, dist in (
        ("typer", "typer", "typer"),
        ("yaml", "pyyaml", "pyyaml"),
        ("rich", "rich", "rich"),
        ("httpx", "httpx", "httpx"),
        ("liteparse", "liteparse", "liteparse"),
    ):
        try:
            m = importlib.import_module(mod)
            check(label, True, _mod_version(m, dist))
        except ImportError:
            check(label, False, "required dependency")
    for mod, extra in (
        ("markitdown", "office"), ("fastmcp", "mcp"), ("docling", "ocr"),
        ("pytest", "test"),
    ):
        try:
            importlib.import_module(mod)
            check(f"extra: {extra}", True, mod)
        except ImportError:
            rows.append((f"extra: {extra}", "MISSING",
                         _install_extra_hint(extra)))

    try:
        from okfsmith.extract import llm as _llm
        reachable = _llm.is_ollama_reachable()
        rows.append(("ollama", "OK" if reachable else "WARN",
                     "reachable" if reachable else
                     f"not reachable at {_llm.DEFAULT_OLLAMA_BASE} — use --no-llm or set OPENAI_API_KEY"))
    except Exception:  # noqa: BLE001
        rows.append(("ollama", "WARN", "could not probe"))

    import tempfile
    try:
        with tempfile.TemporaryDirectory(prefix="okfsmith-doctor-"):
            pass
        rows.append(("tmp writable", "OK", tempfile.gettempdir()))
    except OSError as exc:
        rows.append(("tmp writable", "FAIL", str(exc)))

    table = Table(title="okfsmith doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    for name, status, detail in rows:
        style = {"OK": "green", "MISSING": "yellow", "WARN": "yellow", "FAIL": "red"}[status]
        table.add_row(escape(name), f"[{style}]{status}[/{style}]", escape(detail))
    console.print(table)
