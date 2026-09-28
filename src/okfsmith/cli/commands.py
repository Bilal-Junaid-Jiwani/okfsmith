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
import inspect
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

try:
    # C8: raised by Bundle.load for unreadable (e.g. non-UTF-8) ``.md``
    # files, with the offending filename in the message. Landed by the core
    # agent; the fallback keeps this module working until then.
    from okfsmith.core.bundle import BundleError
except ImportError:  # pragma: no cover - fallback until the C8 change lands
    class BundleError(Exception):
        """Unreadable bundle file (non-UTF-8 ``.md``); filename in message."""

console = Console()

PANEL_BUNDLE = "Bundle"
PANEL_KNOWLEDGE = "Knowledge"
PANEL_SERVE = "Serve"
PANEL_INTERACTIVE = "Interactive"

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


def _warn_api_key_flag() -> None:
    """One-time warning when ``--api-key`` is passed on the command line.

    The key lands in shell history that way; the ``OKFSMITH_API_KEY``
    environment variable is preferred. Printed to stderr, once per process.
    """
    global _api_key_warned
    if _api_key_warned:
        return
    _api_key_warned = True
    typer.echo(
        "Warning: --api-key puts your key in shell history; "
        "prefer the OKFSMITH_API_KEY environment variable.",
        err=True,
    )


_api_key_warned = False


def _fail_json(code: str, message: str, hint: str | None = None) -> NoReturn:
    """Emit a machine-readable error object on stdout and exit 1."""
    payload: dict[str, Any] = {"status": "error", "code": code, "message": message}
    if hint:
        payload["hint"] = hint
    typer.echo(json.dumps(payload, indent=2))
    raise typer.Exit(code=1)


def _jsonable(value: Any) -> Any:
    """Make frontmatter values JSON-serializable.

    datetimes -> ISO 8601; bytes (e.g. ``!!binary`` YAML tags) -> UTF-8 text
    when possible, otherwise a ``{"$binary": <base64>}`` marker object, so
    ``read --format json`` never crashes on non-JSON-native values (H13).
    """
    import base64
    import datetime

    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return {"$binary": base64.b64encode(raw).decode("ascii")}
    if isinstance(value, dict):
        return {_jsonable(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_jsonable(v) for v in value), key=repr)
    return value


def _dump_json(payload: Any) -> None:
    typer.echo(json.dumps(_jsonable(payload), indent=2))


def _plural(count: int, singular: str) -> str:
    """Inflect a count phrase: ``1 result`` / ``2 results`` (L1)."""
    return f"{count} {singular}" if count == 1 else f"{count} {singular}s"


def _valid_cell(status) -> str:
    """Short ``Valid``-column cell for a temporal status.

    Concepts with no temporal frontmatter show ``—`` (not noise); the rest
    show the short status name (``not_yet_valid`` renders as ``future``).
    """
    if not status.has_temporal:
        return "—"
    return {"not_yet_valid": "future"}.get(status.name, status.name)


def _short_dt(value) -> str:
    """Format a parsed temporal datetime compactly: date-only when midnight."""
    from datetime import time as _time

    if value is None:
        return "—"
    if value.time() == _time(0, 0):
        return value.date().isoformat()
    return value.isoformat()


def _temporal_badge(bundle, concept) -> str | None:
    """One-line temporal status badge for ``read`` text output.

    Returns ``None`` for plain concepts with a ``current`` status, so they
    print byte-identical output to before. Never raises on hostile
    frontmatter.
    """
    from okfsmith.core.temporal import (
        SupersessionIndex,
        has_temporal_fields,
        parse_temporal,
        utcnow,
    )

    fm = concept.frontmatter or {}
    status = SupersessionIndex.from_bundle(bundle).status(concept, utcnow())
    if not has_temporal_fields(fm) and status.name == "current":
        # Plain concept, nothing temporal to say: byte-identical output.
        return None
    if status.name == "current":
        window = ""
        valid_from = _short_dt(parse_temporal(fm.get("valid_from")))
        valid_until = _short_dt(parse_temporal(fm.get("valid_until")))
        if valid_from != "—" or valid_until != "—":
            window = f" (valid {valid_from} → {valid_until})"
        return f"[temporal: current{window}]"
    if status.name == "superseded":
        return f"[temporal: superseded by {status.superseded_by}]"
    if status.name == "expired":
        valid_until = _short_dt(parse_temporal(fm.get("valid_until")))
        return f"[temporal: expired (valid_until {valid_until} has passed)]"
    valid_from = _short_dt(parse_temporal(fm.get("valid_from")))
    return f"[temporal: not yet valid (valid_from {valid_from})]"


def _load_bundle_for_read(bundle_path: Path) -> Bundle:
    """Load a bundle, converting unreadable files to a clean CliError (C8).

    ``Bundle.load`` raises :class:`BundleError` (naming the offending file)
    for non-UTF-8 ``.md`` reads; translate it to the standard
    ``error [io-error]`` + hint contract instead of a traceback.
    """
    try:
        return Bundle.load(bundle_path)
    except BundleError as exc:
        raise CliError(
            "io-error",
            f"cannot read bundle '{bundle_path}': {exc}",
            "Fix or remove the unreadable file, or exclude it from the bundle.",
        ) from None


def _check_with_bundle(check: Any, bundle_path: Path, bundle_obj: Bundle) -> Any:
    """Run ``validate.check()``, reusing the already-loaded bundle (M17).

    The validator agent adds a keyword-only ``bundle`` parameter to
    ``check()``; older implementations accept only the path. Passing the
    loaded bundle avoids parsing every file's frontmatter twice.
    """
    try:
        use_bundle_kwarg = "bundle" in inspect.signature(check).parameters
    except (TypeError, ValueError):
        use_bundle_kwarg = False
    try:
        if use_bundle_kwarg:
            return check(bundle_path, bundle=bundle_obj)
        return check(bundle_path)
    except BundleError as exc:
        raise CliError(
            "io-error",
            f"cannot validate bundle '{bundle_path}': {exc}",
            "Fix or remove the unreadable file, or exclude it from the bundle.",
        ) from None


_MISSING_EXTRA_MARKERS = (
    # (message fragment, extra name) — M19: an explicitly named source that
    # needs an uninstalled optional extra must fail loudly, not warn-and-skip.
    ("markitdown is not installed", "office"),
    ("docling is not installed", "ocr"),
)


def _raise_if_missing_extra(path: Path, error: str) -> None:
    """Raise CliError when *error* is a missing-extra parse failure (M19)."""
    lowered = error.lower()
    for marker, extra in _MISSING_EXTRA_MARKERS:
        if marker in lowered:
            raise CliError(
                "missing-extra",
                f"cannot ingest '{path}': {marker}.",
                _install_extra_hint(extra),
            )


def _write_output_file(path: Path, text: str) -> None:
    """Write ``graph --output`` content, creating missing parents (H8).

    A directory target is rejected before this is called; an OSError (e.g.
    an unwritable parent) becomes a clean CliError, never a traceback.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise CliError(
            "io-error",
            f"cannot write output file '{path}': {exc}",
            "Choose a writable --output path.",
        ) from None


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
    if not source.is_dir():
        # H10: FIFOs, /dev/zero, sockets and friends are neither files nor
        # directories — fail cleanly instead of a NotADirectoryError traceback.
        raise CliError(
            "not-a-directory",
            f"source '{source}' is not a file or directory.",
            "Pass a file, or a directory (with --recursive to descend).",
        )
    iterator = source.rglob("*") if recursive else source.iterdir()
    # Reserved bundle files are infrastructure, never knowledge sources.
    try:
        return sorted(
            p for p in iterator if p.is_file() and p.name not in _RESERVED_NAMES
        )
    except OSError as exc:
        raise CliError(
            "io-error",
            f"cannot scan source '{source}': {exc}",
            "Check the directory is readable.",
        ) from None


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
    bundle_path = bundle
    # H11: I/O failures (unwritable dir, read-only filesystem) become
    # error [io-error], never a traceback.
    try:
        bundle_path.mkdir(parents=True, exist_ok=True)
        bundle_obj = Bundle(bundle_path)
        index_path = indexlog.ensure_index(bundle_obj)
        log_path = indexlog.append_log(
            bundle_obj, kind="Creation", message="Bundle created with `okfsmith init`."
        )
    except OSError as exc:
        raise CliError(
            "io-error",
            f"could not initialize bundle in '{bundle_path}': {exc}",
            "Check the path is writable and not on a read-only filesystem.",
        ) from None
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
    explicit: bool = False,
) -> tuple[str, int]:
    """Ingest one file via deterministic sectioning. Returns (status, count).

    *explicit* marks a source the user named directly (vs. one discovered by
    scanning a directory); explicit sources escalate missing-extra failures
    instead of warn-and-skipping (M19).
    """
    digest = sha256_of(path)
    if already_ingested(target, digest):
        return "skipped (already ingested)", 0
    parsed = parse_file(path)
    # M2: parse failures report the real reason first — a corrupt source is
    # not a stub-prevention skip (the dry run already orders it this way).
    error = (parsed.meta or {}).get("error")
    if error:
        if explicit:
            _raise_if_missing_extra(path, str(error))
        return f"skipped ({error})", 0
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
    provider: str | None = None,
    api_base: str | None = None,
    api_key: str | None = None,
    explicit: bool = False,
) -> tuple[str, int]:
    """Ingest one file via the LLM extraction pipeline. Returns (status, count)."""
    parsed = parse_file(path)
    # M19: an explicitly named source that needs an uninstalled extra fails
    # loudly (the no-LLM path does the same via _ingest_no_llm_one).
    error = (parsed.meta or {}).get("error")
    if error and explicit:
        _raise_if_missing_extra(path, str(error))
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
    created = run(
        target,
        sections,
        model=model,
        provider=provider,
        base_url=api_base,
        api_key=api_key,
    )
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
    provider: str | None = typer.Option(
        None,
        "--provider",
        help="LLM provider preset: openrouter, groq, mistral, deepseek, "
        "together, fireworks, deepinfra, anyscale, perplexity, xai, gemini, "
        "openai, agentrouter, lmstudio, ollama (or OKFSMITH_PROVIDER).",
    ),
    api_base: str | None = typer.Option(
        None,
        "--api-base",
        help="Custom OpenAI-compatible base URL, e.g. "
        "https://my-proxy/v1 (or OKFSMITH_API_BASE). Covers Azure OpenAI, "
        "self-hosted vLLM / llama.cpp, or any compat proxy. "
        "Overrides --provider.",
    ),
    api_key: str | None = typer.Option(
        None,
        "--api-key",
        help="API key for the endpoint (or OKFSMITH_API_KEY env var, "
        "preferred — --api-key lands in shell history).",
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
        export OKFSMITH_API_KEY=... OKFSMITH_PROVIDER=groq
        okfsmith ingest ./kb paper.pdf --model llama-3.3-70b-versatile
        okfsmith ingest ./kb paper.pdf --provider openrouter --model anthropic/claude-sonnet-4
    """
    # --- validate everything before any lazy import (review-gate item 4) ---
    if model is not None and no_llm:
        raise typer.BadParameter(
            "--model cannot be combined with --no-llm: no LLM is used in that mode."
        )
    for flag_name, flag_value in (
        ("--provider", provider),
        ("--api-base", api_base),
        ("--api-key", api_key),
    ):
        if flag_value is not None and no_llm:
            raise typer.BadParameter(
                f"{flag_name} cannot be combined with --no-llm: "
                "no LLM is used in that mode."
            )
    if api_key is not None:
        _warn_api_key_flag()
    # H9: a file passed as the bundle is a usage error, not a FileExistsError
    # traceback from Bundle.load's mkdir.
    if bundle.exists() and not bundle.is_dir():
        fail(
            "not-a-directory",
            f"'{bundle}' exists but is not a directory.",
            "Pass a bundle directory (created if missing), not a file.",
        )
    files: list[Path] = []
    explicit_paths: set[Path] = set()
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
        # M19: remember sources the user named directly — they escalate
        # missing-extra parse failures instead of warn-and-skipping.
        if source.is_file():
            explicit_paths.add(source.resolve())
        files.extend(found)

    _parse_file = _lazy_attr("okfsmith.parsers", "parse_file")
    if quiet and "quiet" in inspect.signature(_parse_file).parameters:
        # M27: --quiet suppresses the per-file parse skip notices (parse_file
        # logs them); the error is still recorded in meta["error"] and shown
        # in the summary table. The signature check keeps this working with
        # older parse_file callables that lack the keyword.
        parse_file = functools.partial(_parse_file, quiet=True)
    else:
        parse_file = _parse_file
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

    digest_of = _lazy_attr("okfsmith.parsers.dedup", "sha256_of")

    if dry_run:
        _ingest_dry_run(bundle, files, no_llm=no_llm, parse_file=parse_file,
                        section=section if not no_llm else None, quiet=quiet,
                        # M18: the dry run consults the dedup manifest so it
                        # predicts "already ingested" like the real run does.
                        sha256_of=digest_of if no_llm else None,
                        already_ingested=already_ingested if no_llm else None)
        return

    # L24: an unwritable bundle directory is a clean CliError, not a
    # traceback from mkdir/write_text.
    try:
        target = Bundle.load(bundle)
    except OSError as exc:
        raise CliError(
            "io-error",
            f"cannot open bundle directory '{bundle}': {exc}",
            "Check the path is writable and not on a read-only filesystem.",
        ) from None
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
            digest = ""
            try:
                # H1: hashing happens inside the per-file try so one
                # unreadable file cannot abort the whole batch.
                digest = digest_of(path)[:12]
                explicit = path.resolve() in explicit_paths
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
                        explicit=explicit,
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
                            provider=provider,
                            api_base=api_base,
                            api_key=api_key,
                            explicit=explicit,
                        )
                    except LLMUnavailableError as exc:
                        raise CliError(
                            "llm-unavailable",
                            f"LLM unavailable: {exc}",
                            "Start Ollama ('ollama serve'), set OKFSMITH_PROVIDER / "
                            "OKFSMITH_API_KEY, or retry with --no-llm.",
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
        # L24: bundle-level write failures are a clean CliError, not a
        # traceback (per-file write failures are already caught per file).
        try:
            indexlog.ensure_index(target)
            indexlog.append_log(
                target,
                kind="Update",
                message=(
                    f"Ingested {created_total} draft concept(s) from "
                    f"{len(files) - len(failures)} source file(s)."
                ),
            )
        except OSError as exc:
            raise CliError(
                "io-error",
                f"could not update bundle '{bundle}': {exc}",
                "Check the bundle directory is writable.",
            ) from None
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
    sha256_of: Any = None,
    already_ingested: Any = None,
) -> None:
    """Parse and plan an ingest without writing anything.

    When *sha256_of*/*already_ingested* are given (no-LLM mode), the dedup
    manifest is consulted so a dry run after a real ingest predicts
    "already ingested" instead of phantom draft concepts (M18).
    """
    typer.echo(f"dry run: would ingest {len(files)} file(s) into {bundle} (nothing written)")
    section_fn = section
    too_small_chars = None
    if no_llm:
        sectioning = importlib.import_module("okfsmith.parsers.sectioning")
        section_fn = sectioning.section
        too_small_chars = sectioning.TOO_SMALL_CHARS
    # Bundle() does no I/O — the manifest is read lazily, never written.
    manifest_bundle = (
        Bundle(bundle)
        if (sha256_of is not None and already_ingested is not None)
        else None
    )
    for path in files:
        if manifest_bundle is not None:
            try:
                digest = sha256_of(path)
            except OSError:
                digest = None  # unreadable file: parse_file reports it below
            if digest is not None and already_ingested(manifest_bundle, digest):
                typer.echo(f"  {path}: would skip (already ingested)")
                continue
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
# sync
# ---------------------------------------------------------------------------


@app.command(rich_help_panel=PANEL_KNOWLEDGE)
@_cli
def sync(
    bundle: Path = typer.Argument(
        ..., help="Bundle directory to sync into (created if missing)."
    ),
    sources: list[Path] = typer.Argument(
        ..., help="File(s) or directories to keep in sync with the bundle."
    ),
    no_llm: bool = typer.Option(
        False,
        "--no-llm",
        help="Use deterministic sectioning (okfsmith.parsers) instead of an LLM.",
    ),
    model: str | None = typer.Option(
        None, "--model", help="Model to use for LLM extraction."
    ),
    provider: str | None = typer.Option(
        None,
        "--provider",
        help="LLM provider preset: openrouter, groq, mistral, deepseek, "
        "together, fireworks, deepinfra, anyscale, perplexity, xai, gemini, "
        "openai, agentrouter, lmstudio, ollama (or OKFSMITH_PROVIDER).",
    ),
    api_base: str | None = typer.Option(
        None,
        "--api-base",
        help="Custom OpenAI-compatible base URL (or OKFSMITH_API_BASE). "
        "Overrides --provider.",
    ),
    api_key: str | None = typer.Option(
        None,
        "--api-key",
        help="API key for the endpoint (or OKFSMITH_API_KEY env var, "
        "preferred — --api-key lands in shell history).",
    ),
    recursive: bool = typer.Option(
        False,
        "--recursive",
        help="Recurse into subdirectories when a SOURCE is a directory.",
    ),
    watch: bool = typer.Option(
        False,
        "--watch",
        help="Keep watching: re-run the sync whenever sources change "
        "(polling). Change detection uses an mtime+size fast path plus a "
        "full re-hash every 5 minutes; Ctrl-C stops cleanly.",
    ),
    interval: float = typer.Option(
        5.0,
        "--interval",
        help="Polling interval in seconds for --watch (must be > 0).",
    ),
    poll: bool = typer.Option(
        False,
        "--poll",
        help="One-shot mode: scan once and exit. This is the default; "
        "--watch switches to continuous mode.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Report what would change without writing anything.",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Only print warnings, errors, and the final summary line.",
    ),
    output_format: ValidateFormat = typer.Option(
        ValidateFormat.text, "--format",
        help="Output format: text or json. In --watch mode, json emits one "
        "compact object per line per cycle (JSONL).",
    ),
) -> None:
    """Incrementally sync BUNDLE with SOURCE... (SHA-256 change detection).

    Only new, changed, renamed, or deleted sources are processed: new files
    are ingested, changed files are re-ingested (their old concepts are
    replaced, never duplicated), renamed files keep their concepts, and
    deleted files have their concepts removed. Additions are applied before
    deletions. State lives in ``<bundle>/.okfsmith/sync-state.json``; a sync
    interrupted midway is resumed safely by the next run.

    One-shot by default; ``--watch`` polls for changes instead.

    \b
    Examples:
        okfsmith sync ./kb docs/ --no-llm
        okfsmith sync ./kb docs/ --recursive --no-llm --dry-run
        okfsmith sync ./kb docs/ --no-llm --watch --interval 10
        okfsmith sync ./kb report.pdf --format json
    """
    # --- validate everything before any lazy import (review-gate item 4) ---
    if model is not None and no_llm:
        raise typer.BadParameter(
            "--model cannot be combined with --no-llm: no LLM is used in that mode."
        )
    for flag_name, flag_value in (
        ("--provider", provider),
        ("--api-base", api_base),
        ("--api-key", api_key),
    ):
        if flag_value is not None and no_llm:
            raise typer.BadParameter(
                f"{flag_name} cannot be combined with --no-llm: "
                "no LLM is used in that mode."
            )
    if api_key is not None:
        _warn_api_key_flag()
    if watch and poll:
        raise typer.BadParameter(
            "--watch and --poll are mutually exclusive: --poll is the "
            "default one-shot mode, --watch is continuous."
        )
    if interval <= 0:
        raise typer.BadParameter("--interval must be > 0.")
    if dry_run and watch:
        raise typer.BadParameter(
            "--dry-run cannot be combined with --watch: nothing would "
            "ever be written."
        )
    # H9: a file passed as the bundle is a usage error, not a traceback.
    if bundle.exists() and not bundle.is_dir():
        raise CliError(
            "not-a-directory",
            f"'{bundle}' exists but is not a directory.",
            "Pass a bundle directory (created if missing), not a file.",
        )
    for source in sources:
        if not source.exists():
            raise CliError(
                "source-not-found",
                f"source '{source}' does not exist.",
                "Pass an existing file or directory.",
            )
    # Lazy import: the engine imports this module's helpers at its top
    # level, so it must be imported after this module is fully loaded.
    from okfsmith.cli import sync as _sync_engine

    config = _sync_engine.SyncConfig(
        no_llm=no_llm,
        recursive=recursive,
        dry_run=dry_run,
        quiet=quiet,
        model=model,
        provider=provider,
        api_base=api_base,
        api_key=api_key,
    )
    bundle_path = bundle
    if watch:
        _sync_engine.run_watch(
            bundle_path,
            list(sources),
            config,
            interval=interval,
            output_format=output_format.value,
            quiet=quiet,
        )
        return
    # CliError (bad bundle, LLM outage, ...) is turned into the standard
    # `error [CODE]` + hint by the @_cli wrapper; --format json commands get
    # a JSON error object via the output_format kwarg.
    result = _sync_engine.run_once(bundle_path, list(sources), config)
    _sync_engine.print_result(
        result, bundle_path, list(sources),
        output_format=output_format.value, quiet=quiet,
    )
    summary = result.summary()
    failures = summary["failed"]
    changed = sum(summary[name] for name in ("added", "updated", "renamed", "removed"))
    if result.results and failures and not changed:
        raise CliError(
            "sync-failed",
            "all sources failed to sync.",
            "Run with --dry-run to inspect without writing.",
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
    """Validate a bundle against OKF v0.2 (E001–E004 / W001–W020).

    W001–W015 are the spec's advisory warnings; W016–W020 are okfsmith's
    temporal-model advisories (valid_from / valid_until / supersedes /
    last_verified). Warnings never affect conformance.

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
    # M17: load the bundle once and hand it to check() (when the validator
    # supports the `bundle` keyword) so frontmatter isn't parsed twice; the
    # same object feeds the concept count below. C8: unreadable files become
    # error [io-error], never a traceback.
    bundle_path = bundle
    bundle_obj = _load_bundle_for_read(bundle_path)
    result = _check_with_bundle(check, bundle_path, bundle_obj)
    errors = [finding.as_dict() for finding in result.errors]
    warnings = [finding.as_dict() for finding in result.warnings]
    n_concepts = sum(1 for _ in bundle_obj.iter_concepts())

    if as_json:
        status = "invalid" if errors or (strict and warnings) else "conformant"
        _dump_json({
            "status": status,
            # L25: the count key is standardized on "count"; "concepts" is a
            # deprecated alias kept for back-compat.
            "count": n_concepts,
            "concepts": n_concepts,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "errors": errors,
            "warnings": warnings,
        })
    else:
        _print_report(errors, warnings, strict=strict)

    if errors or (strict and warnings):
        raise typer.Exit(code=1)


def _print_report(errors: list[dict], warnings: list[dict], *, strict: bool = False) -> None:
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
    elif warnings and strict:
        # M7: under --strict warnings are failures (exit 1) — never print
        # "Conformant" for a failing run.
        typer.echo(
            f"INVALID under --strict: {len(warnings)} warning(s) "
            "treated as failures."
        )
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
    bundle = _load_bundle_for_read(bundle_path)
    from okfsmith.core.temporal import SupersessionIndex, utcnow

    sindex = SupersessionIndex.from_bundle(bundle)
    moment = utcnow()
    rows = []
    for concept in bundle.iter_concepts():
        ctype = str(concept.frontmatter.get("type") or "")
        tier = _spec.trust_tier(concept.frontmatter)
        if type_filter and ctype.casefold() != type_filter.casefold():
            continue
        if tier_filter and tier.casefold() != tier_filter.casefold():
            continue
        status = sindex.status(concept, moment)
        rows.append({
            "id": concept.id,
            "type": ctype,
            "title": str(concept.frontmatter.get("title") or ""),
            "tier": tier,
            "temporal_status": status.name,
            "valid": _valid_cell(status),
        })
    if as_json:
        _dump_json({
            "concepts": [
                {k: row[k] for k in ("id", "type", "title", "tier", "temporal_status")}
                for row in rows
            ],
            "count": len(rows),
        })
        return
    table = Table(title=f"Concepts in {bundle_path}")
    # IDs must never truncate: users copy-paste them into `read`.
    table.add_column("ID", no_wrap=True, overflow="fold")
    table.add_column("Type")
    table.add_column("Title")
    table.add_column("Trust tier")
    table.add_column("Valid")
    for row in rows:
        table.add_row(
            escape(row["id"]),
            escape(row["type"]),
            escape(row["title"]),
            escape(row["tier"]),
            escape(row["valid"]),
        )
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
    bundle = _load_bundle_for_read(bundle_path)
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
    from okfsmith.core.temporal import SupersessionIndex, utcnow

    temporal_status = SupersessionIndex.from_bundle(bundle).status(
        concept, utcnow()
    ).name
    if as_json:
        _dump_json({
            "id": concept.id,
            "frontmatter": concept.frontmatter,
            "body": concept.body,
            "temporal_status": temporal_status,
        })
    else:
        typer.echo(_fm.serialize_frontmatter(concept.frontmatter, concept.body))
        badge = _temporal_badge(bundle, concept)
        if badge is not None:
            typer.echo(f"\n{badge}")


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


@app.command(rich_help_panel=PANEL_KNOWLEDGE)
@_cli
def search(
    bundle: Path = typer.Argument(..., help="Bundle directory to search."),
    query: str = typer.Argument(
        ..., help="Search query (quote multi-word queries)."
    ),
    limit: int = typer.Option(
        10, "--limit", "-n", help="Maximum number of results (must be >= 1)."
    ),
    type_filter: str | None = typer.Option(
        None, "--type", help="Only show concepts of this type."
    ),
    tier_filter: str | None = typer.Option(
        None, "--tier",
        help=f"Only show concepts with this trust tier ({', '.join(TRUST_TIERS)}).",
    ),
    as_of: str | None = typer.Option(
        None,
        "--as-of",
        help="Replay search at a past/future instant (ISO-8601 date or "
        "datetime): validity windows and supersession chains are evaluated "
        "at that instant instead of now.",
    ),
    include_superseded: bool = typer.Option(
        False,
        "--include-superseded",
        help="Also show concepts superseded by a newer concept "
        "(demoted, ranked last; never deleted).",
    ),
    output_format: ValidateFormat = typer.Option(
        ValidateFormat.text, "--format", help="Output format: text or json."
    ),
) -> None:
    """Full-text search over a bundle (BM25 ranking).

    Retrieval is conflict-aware: current concepts rank first, concepts
    outside their validity window are demoted (still shown, marked), and
    superseded concepts are hidden unless --include-superseded is given.
    Within one currency group, ties break by trust tier
    (human-reviewed > machine-confirmed > unverified), then by
    last_verified recency — recency alone never demotes a trusted concept.

    \b
    Examples:
        okfsmith search ./kb "knowledge graph"
        okfsmith search ./kb "quarterly revenue" --tier human-reviewed -n 5
        okfsmith search ./kb "api design" --format json
        okfsmith search ./kb "refund policy" --as-of 2025-06-01
        okfsmith search ./kb "refund policy" --include-superseded
    """
    as_json = output_format == "json"
    if not query.strip():
        raise typer.BadParameter("query must not be empty.")
    if limit < 1:
        raise typer.BadParameter("--limit must be >= 1.")
    if tier_filter is not None and tier_filter.casefold() not in TRUST_TIERS:
        raise typer.BadParameter(
            f"--tier '{tier_filter}' is not one of: {', '.join(TRUST_TIERS)}"
        )
    moment = None
    if as_of is not None:
        from okfsmith.core import temporal as _temporal

        moment = _temporal.parse_temporal(as_of)
        if moment is None:
            raise typer.BadParameter(
                f"--as-of '{as_of}' is not an ISO-8601 date or datetime."
            )
    try:
        _require_bundle_dir(bundle)
    except CliError as exc:
        _handle_cli_error(exc, as_json)
    try:
        # The search engine is built concurrently by another agent; code to
        # this import and fail cleanly (never a traceback) if it is absent.
        from okfsmith.search import search_bundle_detailed
    except ImportError as exc:
        raise CliError(
            "search-unavailable",
            "the search engine (okfsmith.search) is not available in this "
            "installation.",
            "Reinstall okfsmith; if the problem persists, file a bug report.",
        ) from exc
    bundle_path = bundle
    bundle = _load_bundle_for_read(bundle_path)
    from okfsmith.core.temporal import SupersessionIndex

    result = search_bundle_detailed(
        bundle,
        query,
        limit=limit,
        as_of=moment,
        include_superseded=include_superseded,
    )
    moment = result.as_of
    sindex = SupersessionIndex.from_bundle(bundle)
    rows = []
    for score, concept in result.hits:
        ctype = str(concept.frontmatter.get("type") or "")
        tier = _spec.trust_tier(concept.frontmatter)
        if type_filter and ctype.casefold() != type_filter.casefold():
            continue
        if tier_filter and tier.casefold() != tier_filter.casefold():
            continue
        status = sindex.status(concept, moment)
        # Current concepts show a blank Valid cell; demoted ones are marked.
        if status.name == "superseded":
            mark = f"superseded→{status.superseded_by}"
        elif status.name == "expired":
            mark = "expired"
        elif status.name == "not_yet_valid":
            mark = "future"
        else:
            mark = ""
        rows.append({
            "id": concept.id,
            "type": ctype,
            "title": str(concept.frontmatter.get("title") or ""),
            "tier": tier,
            "score": score,
            "temporal_status": status.name,
            "superseded_by": status.superseded_by,
            "valid_mark": mark,
        })
    if as_json:
        _dump_json({
            "query": query,
            "as_of": moment.isoformat(),
            "results": [
                {
                    key: row[key]
                    for key in (
                        "id", "type", "title", "tier", "score",
                        "temporal_status", "superseded_by",
                    )
                }
                for row in rows
            ],
            "count": len(rows),
            "superseded_hidden": result.superseded_hidden,
        })
        return
    table = Table(title=f"Search results in {bundle_path}")
    table.add_column("Score", justify="right")
    # IDs must never truncate: users copy-paste them into `read`.
    table.add_column("ID", no_wrap=True, overflow="fold")
    table.add_column("Type")
    table.add_column("Title")
    table.add_column("Tier")
    table.add_column("Valid")
    for row in rows:
        table.add_row(
            f"{row['score']:.3f}",
            escape(row["id"]),
            escape(row["type"]),
            escape(row["title"]),
            escape(row["tier"]),
            escape(row["valid_mark"]),
        )
    console.print(table)
    typer.echo(_plural(len(rows), "result"))
    if result.superseded_hidden:
        typer.echo(
            f"hint: {_plural(result.superseded_hidden, 'superseded result')} "
            "hidden — use --include-superseded to show them.",
            err=True,
        )
    if not rows:
        typer.echo(
            f"hint: no concepts matched '{query}'. Try different terms, or "
            f"browse with 'okfsmith list {bundle_path}'.",
            err=True,
        )


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
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite the --output file if it already exists.",
    ),
) -> None:
    """Show the concept link graph (nodes, edges, orphans, dead links).

    \b
    Examples:
        okfsmith graph ./kb
        okfsmith graph ./kb --format html --output graph.html
        okfsmith graph ./kb --format json --output graph.json --force
    """
    as_json = output_format == "json"
    try:
        _require_bundle_dir(bundle)
    except CliError as exc:
        _handle_cli_error(exc, as_json)
    bundle_path = bundle
    # Resolve the output target up front so every format enforces the same
    # rules: a directory is never a valid target (H8), and an existing file
    # — including the default <bundle>/viz.html — is never overwritten
    # without --force (H7).
    target: Path | None = output
    if output_format == "html" and target is None:
        target = bundle_path / "viz.html"
    if target is not None:
        if target.exists() and not target.is_file():
            fail(
                "invalid-output",
                f"--output '{target}' is not a file path.",
                "Give a path to a file (it will be created), not a directory.",
            )
        if target.is_file() and not force:
            fail(
                "output-exists",
                f"--output '{target}' already exists.",
                "Pass --force to overwrite it, or choose a different path.",
            )
    bundle = _load_bundle_for_read(bundle_path)
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
        if target is not None:
            _write_output_file(
                target, json.dumps(_jsonable(payload), indent=2)
            )
            typer.echo(f"Wrote {target}")
        else:
            _dump_json(payload)
    elif output_format == "mermaid":
        text = _links.mermaid_flowchart(data)
        if target is not None:
            _write_output_file(target, text)
            typer.echo(f"Wrote {target}")
        else:
            typer.echo(text, nl=False)
    elif output_format == "html":
        # render_html(root, output) -> Path; target is always set for html.
        assert target is not None
        render_html = _lazy_attr("okfsmith.viz", "render_html")
        written = render_html(bundle_path, target)
        typer.echo(f"Wrote {written}")
    elif output_format == "text":
        if target is not None:
            # Capture the text report and write it to the file.
            import io
            from contextlib import redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf):
                _print_graph_text(bundle, data)
            _write_output_file(target, buf.getvalue())
            typer.echo(f"Wrote {target}")
        else:
            _print_graph_text(bundle, data)


def _print_graph_text(bundle: Bundle, data: dict) -> None:
    typer.echo(
        f"{_plural(len(data['nodes']), 'concept')}, "
        f"{_plural(len(data['edges']), 'link')}, "
        f"{_plural(len(data['dead_links']), 'dead link')}."
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


def doctor_checks() -> list[tuple[str, str, str]]:
    """Run every ``okfsmith doctor`` check; return ``(name, status, detail)`` rows.

    Status is one of ``OK`` / ``MISSING`` / ``WARN`` / ``FAIL``. Extracted from
    :func:`doctor` so non-CLI callers (e.g. the web dashboard) can wrap the
    exact same checks instead of reimplementing them.
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

    # LLM backend resolution summary (no network probing here; the ollama
    # row above covers reachability). Keys are never displayed — only
    # whether one is configured.
    try:
        from okfsmith.extract import llm as _llm
        cfg = _llm.resolve_llm_config()
        rows.append(("llm provider", "OK", cfg.provider))
        rows.append(("llm base URL", "OK", cfg.base_url or _llm.DEFAULT_OLLAMA_BASE))
        rows.append(("llm model", "OK", cfg.model))
        rows.append((
            "llm api key",
            "OK" if cfg.api_key else "MISSING",
            f"{_llm.key_status(cfg.api_key)} (via {cfg.key_source})"
            if cfg.api_key
            else "not needed for local Ollama; set OKFSMITH_API_KEY for hosted providers",
        ))
    except Exception as exc:  # noqa: BLE001 — e.g. unknown OKFSMITH_PROVIDER
        rows.append(("llm provider", "FAIL", str(exc)))

    import tempfile
    try:
        with tempfile.TemporaryDirectory(prefix="okfsmith-doctor-"):
            pass
        rows.append(("tmp writable", "OK", tempfile.gettempdir()))
    except OSError as exc:
        rows.append(("tmp writable", "FAIL", str(exc)))

    return rows


@app.command(rich_help_panel=PANEL_BUNDLE)
@_cli
def doctor() -> None:
    """Check the environment: dependencies, extras, Ollama, writability.

    Reports OK / MISSING / WARN per check so a broken setup is diagnosable
    in one command.
    """
    rows = doctor_checks()
    table = Table(title="okfsmith doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    for name, status, detail in rows:
        style = {"OK": "green", "MISSING": "yellow", "WARN": "yellow", "FAIL": "red"}[status]
        table.add_row(escape(name), f"[{style}]{status}[/{style}]", escape(detail))
    console.print(table)


# ---------------------------------------------------------------------------
# chat
# ---------------------------------------------------------------------------


@app.command(rich_help_panel=PANEL_INTERACTIVE)
@_cli
def chat(
    bundle: Path | None = typer.Argument(
        None,
        help="Bundle directory to chat with (default: the current directory, "
        "if it is a bundle).",
    ),
    model: str | None = typer.Option(
        None, "--model", help="Model to use for generative answers."
    ),
    provider: str | None = typer.Option(
        None,
        "--provider",
        help="LLM provider preset: openrouter, groq, mistral, deepseek, "
        "together, fireworks, deepinfra, anyscale, perplexity, xai, gemini, "
        "openai, agentrouter, lmstudio, ollama (or OKFSMITH_PROVIDER).",
    ),
    api_base: str | None = typer.Option(
        None,
        "--api-base",
        help="Custom OpenAI-compatible base URL, e.g. "
        "https://my-proxy/v1 (or OKFSMITH_API_BASE). Covers Azure OpenAI, "
        "self-hosted vLLM / llama.cpp, or any compat proxy. "
        "Overrides --provider.",
    ),
    api_key: str | None = typer.Option(
        None,
        "--api-key",
        help="API key for the endpoint (or OKFSMITH_API_KEY env var, "
        "preferred -- --api-key lands in shell history).",
    ),
    no_llm: bool = typer.Option(
        False,
        "--no-llm",
        help="Extractive mode: answer from keyword-matched concept excerpts, "
        "no LLM involved.",
    ),
) -> None:
    """Chat with a bundle in natural language (Claude Code / Gemini CLI style).

    Ask questions; okfsmith retrieves the relevant concepts and answers with
    ``[concept-id]`` citations. With no reachable LLM it stays useful in
    extractive mode. Slash commands expose bundle operations inline —
    type ``/help`` inside the chat to see them.

    Any hosted model works via ``--provider`` presets — ``openrouter``
    is the flagship: one key routes to hundreds of models
    (``--model anthropic/claude-sonnet-4`` style IDs). Also: groq, mistral,
    deepseek, together, fireworks, deepinfra, anyscale, perplexity, xai,
    gemini, openai, agentrouter, lmstudio, ollama. Put the key in
    ``OKFSMITH_API_KEY`` (``AGENTROUTER_API_KEY`` works for the agentrouter
    preset), never on the command line in scripts. Anything else (Azure
    OpenAI, self-hosted vLLM / llama.cpp, any compat proxy) works via
    ``--api-base``. Note: Anthropic's native API is not OpenAI-compatible —
    it needs a compat proxy (or the ``openrouter`` preset).

    \b
    Examples:
        okfsmith chat ./kb
        okfsmith chat ./kb --no-llm
        okfsmith chat ./kb --model qwen3:8b
        export OKFSMITH_API_KEY=... OKFSMITH_PROVIDER=groq
        okfsmith chat ./kb --model llama-3.3-70b-versatile
        okfsmith chat ./kb --provider openrouter --model anthropic/claude-sonnet-4
        printf '/list\\n/exit\\n' | okfsmith chat ./kb
    """
    if model is not None and no_llm:
        raise typer.BadParameter(
            "--model cannot be combined with --no-llm: no LLM is used in that mode."
        )
    # Lazy import: okfsmith.cli.chat imports this module for the slash-command
    # implementations, so importing it at top level would be circular.
    # _require_bundle_dir raises CliError; the @_cli wrapper turns it into
    # the standard `error [CODE]` + hint and exits.
    for flag_name, flag_value in (
        ("--provider", provider),
        ("--api-base", api_base),
        ("--api-key", api_key),
    ):
        if flag_value is not None and no_llm:
            raise typer.BadParameter(
                f"{flag_name} cannot be combined with --no-llm: "
                "no LLM is used in that mode."
            )
    if api_key is not None:
        _warn_api_key_flag()
    root = _require_bundle_dir(bundle or Path("."))
    from okfsmith.cli import chat as _chat_engine
    from okfsmith.extract.llm import LLMError as _LLMError

    try:
        code = _chat_engine.run_chat(
            root,
            model=model,
            no_llm=no_llm,
            provider=provider,
            api_base=api_base,
            api_key=api_key,
        )
    except BundleError as exc:
        # C8: chat-adjacent bundle read — unreadable files fail cleanly.
        raise CliError(
            "io-error",
            f"cannot read bundle '{root}': {exc}",
            "Fix or remove the unreadable file, or exclude it from the bundle.",
        ) from None
    except _LLMError as exc:
        # Configuration mistakes (e.g. unknown --provider) fail loudly here
        # rather than silently degrading to extractive mode.
        fail(
            "bad-llm-config",
            str(exc),
            "Use --provider with a valid preset name, or set "
            "OKFSMITH_PROVIDER / OKFSMITH_API_BASE.",
        )
    if code:
        raise typer.Exit(code=code)


# ---------------------------------------------------------------------------
# eval
# ---------------------------------------------------------------------------


@app.command(name="eval", rich_help_panel=PANEL_KNOWLEDGE)
@_cli
def eval_bundle(
    bundle: Path = typer.Argument(..., help="Bundle directory to evaluate."),
    top_k: int = typer.Option(
        5, "--top-k", "-n",
        help="Concepts retrieved per question (must be >= 1).",
    ),
    fail_under: float = typer.Option(
        0.0, "--fail-under",
        help="CI gate: exit 1 when the overall score (0-100) is below this.",
    ),
    metric_threshold: float | None = typer.Option(
        None, "--metric-threshold",
        help="Per-metric pass threshold (0-1): a question fails when any "
        "of the three RAG Triad metrics scores below it. Default: 0.6 for "
        "context relevancy and faithfulness, 0.4 for answer relevancy "
        "(the heuristic's natural scale is lower).",
    ),
    as_of: str | None = typer.Option(
        None,
        "--as-of",
        help="Replay retrieval at a past/future instant (ISO-8601 date or "
        "datetime): validity windows and supersession chains are evaluated "
        "at that instant instead of now.",
    ),
    include_superseded: bool = typer.Option(
        False,
        "--include-superseded",
        help="Also retrieve concepts superseded by a newer concept "
        "(demoted, ranked last; never deleted).",
    ),
    no_llm: bool = typer.Option(
        False,
        "--no-llm",
        help="Force heuristic scoring (no LLM judge), even when a provider "
        "is configured.",
    ),
    model: str | None = typer.Option(
        None, "--model", help="Model to use for the LLM judge."
    ),
    provider: str | None = typer.Option(
        None,
        "--provider",
        help="LLM provider preset: openrouter, groq, mistral, deepseek, "
        "together, fireworks, deepinfra, anyscale, perplexity, xai, gemini, "
        "openai, agentrouter, lmstudio, ollama (or OKFSMITH_PROVIDER).",
    ),
    api_base: str | None = typer.Option(
        None,
        "--api-base",
        help="Custom OpenAI-compatible base URL, e.g. "
        "https://my-proxy/v1 (or OKFSMITH_API_BASE). Overrides --provider.",
    ),
    api_key: str | None = typer.Option(
        None,
        "--api-key",
        help="API key for the endpoint (or OKFSMITH_API_KEY env var, "
        "preferred — --api-key lands in shell history).",
    ),
    init_sample: bool = typer.Option(
        False,
        "--init-sample",
        help="Write a starter <bundle>/eval/golden.json derived from the "
        "bundle's own concepts, then exit.",
    ),
    output_format: ValidateFormat = typer.Option(
        ValidateFormat.text, "--format", help="Output format: text or json."
    ),
) -> None:
    """Evaluate a bundle against a golden Q&A set (RAG Triad + CI gating).

    The golden set lives at ``<bundle>/eval/golden.json`` (see
    ``--init-sample``). Each question is answered with the shared BM25
    retrieval engine (same ranking as ``search``, chat, and MCP — including
    temporal supersession hiding), then scored on context relevancy,
    faithfulness, and answer relevancy. Every score is labeled
    ``heuristic`` (keyless) or ``llm-judge`` (an LLM backend was reachable);
    a failing judge degrades that metric to the heuristic, never the
    reverse. Failing questions are diagnosed as ``retrieval`` vs
    ``generation`` failures. ``--fail-under <0-100>`` gates CI: exit 0 when
    the overall score clears it, exit 1 when it doesn't.

    \b
    Examples:
        okfsmith eval ./kb --init-sample        # write a starter golden set
        okfsmith eval ./kb                      # heuristic scoring, no LLM
        okfsmith eval ./kb --no-llm             # force heuristic mode
        okfsmith eval ./kb --format json         # machine-readable report
        okfsmith eval ./kb --fail-under 70       # CI gate: exit 1 below 70
        okfsmith eval ./kb --as-of 2025-06-01   # temporal replay
    """
    as_json = output_format == "json"
    if model is not None and no_llm:
        raise typer.BadParameter(
            "--model cannot be combined with --no-llm: no LLM is used in that mode."
        )
    for flag_name, flag_value in (
        ("--provider", provider),
        ("--api-base", api_base),
        ("--api-key", api_key),
    ):
        if flag_value is not None and no_llm:
            raise typer.BadParameter(
                f"{flag_name} cannot be combined with --no-llm: "
                "no LLM is used in that mode."
            )
    if api_key is not None:
        _warn_api_key_flag()
    if top_k < 1:
        raise typer.BadParameter("--top-k must be >= 1.")
    if not 0.0 <= fail_under <= 100.0:
        raise typer.BadParameter("--fail-under must be between 0 and 100.")
    if metric_threshold is not None and not 0.0 <= metric_threshold <= 1.0:
        raise typer.BadParameter("--metric-threshold must be between 0 and 1.")
    moment = None
    if as_of is not None:
        from okfsmith.core import temporal as _temporal

        moment = _temporal.parse_temporal(as_of)
        if moment is None:
            raise typer.BadParameter(
                f"--as-of '{as_of}' is not an ISO-8601 date or datetime."
            )
    try:
        _require_bundle_dir(bundle)
    except CliError as exc:
        _handle_cli_error(exc, as_json)
    bundle_path = bundle

    from okfsmith import eval as _eval

    def _eval_error(exc: _eval.EvalError) -> NoReturn:
        if as_json:
            _fail_json(exc.code, exc.message, exc.hint)
        fail(exc.code, exc.message, exc.hint)
        raise AssertionError("unreachable")  # pragma: no cover

    if init_sample:
        bundle_obj = _load_bundle_for_read(bundle_path)
        concepts = list(bundle_obj.iter_concepts())
        try:
            written = _eval.write_sample_golden(bundle_path, concepts)
        except _eval.EvalError as exc:
            _eval_error(exc)
        typer.echo(f"Wrote starter golden set to {written}")
        typer.echo(
            "hint: edit it into curated questions, then run "
            f"'okfsmith eval {bundle_path}'."
        )
        return

    bundle_obj = _load_bundle_for_read(bundle_path)
    try:
        report = _eval.run_eval(
            bundle_obj,
            bundle_path,
            top_k=top_k,
            metric_threshold=metric_threshold,
            fail_under=fail_under,
            as_of=moment,
            include_superseded=include_superseded,
            no_llm=no_llm,
            model=model,
            provider=provider,
            api_base=api_base,
            api_key=api_key,
        )
    except _eval.EvalError as exc:
        _eval_error(exc)

    if as_json:
        _dump_json(report.as_dict())
    else:
        _print_eval_text(report)
    # CI gating: exit 1 when the overall score misses the threshold.
    if report.overall() < fail_under:
        raise typer.Exit(code=1)


def _print_eval_text(report: Any) -> None:
    """Rich per-question table plus retrieval-vs-generation diagnosis."""
    judge_note = {
        "heuristic": "heuristic mode — keyless scoring "
        "(no metric was LLM-judged)",
        "llm-judge": "LLM judge mode — all scores LLM-judged",
        "mixed": "mixed mode — some metrics LLM-judged, others fell back "
        "to heuristics (see per-score detail)",
    }[report.judge_mode]
    typer.echo(
        f"Evaluated {report.bundle}: {len(report.questions)} question(s), "
        f"top-k={report.top_k}, {judge_note}."
    )
    table = Table(title="Golden-set results")
    table.add_column("Question", no_wrap=True, overflow="fold")
    table.add_column("Ctx rel.", justify="right")
    table.add_column("Faith.", justify="right")
    table.add_column("Ans rel.", justify="right")
    table.add_column("Result")
    table.add_column("Diagnosis")
    for question in report.questions:
        cells = []
        for name in ("context_relevancy", "faithfulness", "answer_relevancy"):
            score = question.scores[name]
            marker = "🤖" if score.method == "llm-judge" else "⚙"
            passed = score.value >= report.metric_thresholds[name]
            style = "green" if passed else "red"
            cells.append(
                f"[{style}]{score.value:.2f}[/{style}] {marker}"
            )
        result = (
            "[green]PASS[/green]" if question.passed else "[red]FAIL[/red]"
        )
        diagnosis = question.diagnosis or "—"
        table.add_row(
            escape(question.id), *cells, result, escape(diagnosis)
        )
    console.print(table)
    typer.echo("Legend: 🤖 llm-judge · ⚙ heuristic (keyless)")
    # The actionable part: every failing question, with its diagnosis.
    failures = [q for q in report.questions if not q.passed]
    if failures:
        typer.echo("\nFailing questions:")
        for question in failures:
            typer.echo(
                f"  - {question.id}: {question.diagnosis} — "
                f"{question.diagnosis_reason}"
            )
            if question.missing_must_cite:
                typer.echo(
                    "    missing must_cite: "
                    + ", ".join(question.missing_must_cite)
                )
    # Golden-set sanity notes: non-gating, but worth a human look.
    warned = [q for q in report.questions if q.warnings]
    if warned:
        typer.echo("\nGolden-set warnings (do not affect the gate):")
        for question in warned:
            for warning in question.warnings:
                typer.echo(f"  ! {question.id}: {warning}")
    means = report.metric_means()
    passed = sum(1 for q in report.questions if q.passed)
    typer.echo(
        f"\nOverall: {report.overall():.1f}/100 "
        f"(ctx {means['context_relevancy']:.2f} · "
        f"faith {means['faithfulness']:.2f} · "
        f"ans {means['answer_relevancy']:.2f}) — "
        f"{passed}/{len(report.questions)} passed."
    )
    if report.fail_under > 0:
        gate = "PASS" if report.verdict() == "pass" else "FAIL"
        typer.echo(
            f"CI gate --fail-under {report.fail_under}: {gate} "
            f"(overall {report.overall():.1f})."
        )
