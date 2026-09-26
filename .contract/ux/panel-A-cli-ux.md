# UX Panel A — CLI UX/DX Audit

**Panel:** 3 senior CLI-UX designers, one voice · **Date:** 2026-09-26
**Scope:** `okfsmith` CLI UX/DX only — command/flag naming, `--help` quality, error messages + exit codes, output design, progress indication, defaults, destructive-action guards, cross-command consistency.
**Audited:** `/tmp/wt-cli` branch `feat/cli` (`src/okfsmith/cli/commands.py`, `src/okfsmith/cli/app.py`), executed live via `CliRunner` (7 commands: `init`, `ingest`, `validate`, `list`, `read`, `graph`, `mcp`).
**Bar:** best-in-class or nothing — measured against `uv`, `ruff`, `gh`, `stripe` CLI help/error/output UX.

## (1) VERDICT: **CHANGES-REQUIRED**

1 blocker, 6 majors, 10 minors. The CLI is well-structured (rich help panels, `error:` prefix convention, sensible exit codes in most paths), but it ships a **broken quickstart** (README's `ingest ./kb <source>` vs the real `ingest <source> --bundle`), silently drops conflicting flags, overwrites bundle files under `--force` without warning, and gives long LLM ingestions zero progress feedback. Not shippable at this bar until the blocker + majors are fixed.

## (2) Findings

| # | Severity | Location | Issue | Concrete fix spec (implement verbatim) |
|---|----------|----------|-------|----------------------------------------|
| B1 | **blocker** | `ingest` signature + README quickstart | README quickstart (`okfsmith init ./kb` → `okfsmith ingest ./kb docs/quarterly-report.pdf`) and README command table (`ingest ./kb <source>…`) show the bundle as a **positional** arg, but the CLI requires `ingest SOURCE --bundle`. Copy-paste onboarding fails with `Missing option '--bundle'`. Also inconsistent with the other 5 commands, which all take the bundle as a positional `directory`. | Make the bundle a **positional** argument on `ingest` and `mcp`, matching the README and sibling commands: `okfsmith ingest <source> <directory>`, `okfsmith mcp <directory>`. Keep `--bundle` as a deprecated hidden alias that errors with `error: --bundle is deprecated; pass the bundle directory positionally, e.g. 'okfsmith ingest docs/ ./kb'.` (exit 2). Update all `--help` text accordingly. |
| M1 | major | `validate --format`, `graph --format` | `--format` is a free `str` validated by hand, failing **late** with a custom exit-1 message. Best-in-class (`gh`, `stripe`) uses an enum: bad values are usage errors (exit 2), get shell completion, and appear in `--help`. Worse: `validate` checks the format **after** the lazy slice import, so `validate ./kb --format yaml` reports the slice as missing instead of the format error. | Use `typer.Option("text", "--format", click_type=typer.Choice(["text","json"]))` (and `["text","json","mermaid","html"]` for `graph`). Validate **all** local inputs (format choice, arg presence) before any lazy slice import in every command. |
| M2 | major | `ingest --model` + `--no-llm` | Conflicting flags are silently accepted: `--model gpt-x --no-llm` ignores `--model` with no word to the user. Silent flag-dropping is a classic DX trust-killer. | In `ingest`, before any work: `if no_llm and model is not None: typer.echo("error: --model has no effect with --no-llm (deterministic sectioning uses no model).", err=True); raise typer.Exit(2)`. |
| M3 | major | `ingest` (long runs) | LLM extraction over N files can take minutes; the CLI prints **nothing** until the final summary table. No progress, no ETA, no per-file status. `uv`/`stripe` stream progress for anything over ~1s. | Wrap the per-file loop in `rich.progress.Progress` (spinner + bar + `"{task.completed}/{task.total} files"` + elapsed). Print one line per completed file (`✓`/`✗`) as it finishes; keep the summary table at the end. Respect `--quiet` (add the flag; suppresses the bar, keeps the table) and auto-disable when stdout is not a TTY. |
| M4 | major | `init --force` | `--force` **silently overwrites** `index.md` and `log.md` (verified: a hand-written `index.md` was destroyed with no warning, no backup, no confirmation). The non-empty guard exists, but `--force` gives no indication it destroys files. | On `--force` with an existing non-empty directory: print `warning: --force will overwrite index.md and log.md in '<dir>'.` and require interactive confirmation (`typer.confirm("Scaffold anyway?", abort=True)`) unless `--yes` is passed. Add `--yes` flag (`-y`), help text: `"Answer yes to all prompts (use with --force in scripts)."`. Never silently destroy user files. |
| M5 | major | `mcp --transport` | Free-string `--transport` with vacuous help (`"MCP transport to use."` — doesn't say which transports exist); invalid values pass through to the slice and fail deep. | `typer.Option("stdio", "--transport", click_type=typer.Choice(["stdio"]))` (extend the choice list when sse/http land) with help `"MCP transport to use. [choices: stdio]"`. |
| M6 | major | `ingest` validation order | `ingest` lazy-imports the extraction slice **before** validating the target bundle (`Bundle.load(bundle)` runs after `_lazy_attr`). With a bad `--bundle` path the user gets a misleading "slice not available" error instead of "bundle doesn't exist". | Order every command as: (1) parse/validate local args and flags, (2) validate local paths (`_require_dir`, source exists, non-empty), (3) lazy-import slices, (4) do work. |
| m1 | minor | `_require_dir` | Says `'<path>' does not exist` when the path exists but is a **file** — misleading. | Distinguish: `if not path.exists(): error "'{p}' does not exist." elif not path.is_dir(): error "'{p}' is not a directory."` Both exit 1. |
| m2 | minor | `read`, `list`, `validate`, `graph` | No check that `directory` is actually a bundle. `read /tmp foo` → `concept 'foo' not found in '/tmp'` instead of telling the user `/tmp` isn't a bundle. | In `_require_dir`-style helper `_require_bundle(path)`: if `(path / "index.md")` missing → `error: '{p}' is not an OKF bundle (no index.md). Run 'okfsmith init {p}' to create one.` exit 1. Use in all five bundle-taking commands. |
| m3 | minor | `list --type` / `--tier` | Unknown filter values (`--tier platinum`) produce a silently empty table, exit 0. User can't tell "no matches" from "typo". | Validate `--tier` against the known trust-tier set (case-insensitive) → exit 2 `error: unknown trust tier 'platinum' (expected one of: …)`. For `--type`, when the result set is empty print `no concepts match --type 'x'.` to stderr instead of a bare empty table. |
| m4 | minor | `list` empty bundle | Empty table + `0 concept(s)` with no guidance. | When `shown == 0` and no filters: after the table, print `No concepts yet. Run 'okfsmith ingest <source> <directory>' to add some.` |
| m5 | minor | `read` | No machine-readable output; agents/MCP consumers must parse raw markdown. | Add `--format text|json` (Choice, default `text`); `json` emits `{"id","frontmatter","body"}` via `json.dumps`. |
| m6 | minor | `graph --output` | Help says `default: <bundle>/viz.html` but the positional is named `directory` — terminology mismatch; also `--output` is silently ignored unless `--format html`. | Rename help to `default: <directory>/viz.html`; if `--output` is passed with a non-html format → exit 2 `error: --output only applies with --format html.` |
| m7 | minor | `validate --format json` | Emits `{"errors": [...], "warnings": [...]}` with no top-level status — every consumer re-derives it. | Emit `{"ok": bool, "error_count": n, "warning_count": n, "errors": [...], "warnings": [...]}`. |
| m8 | minor | `graph` text mode | Uses hand-rolled `typer.echo` lines while `list`/`validate` use rich tables — inconsistent output design language. | Render orphans/dead-links as rich tables matching `validate`'s report style (Code/File/Message columns → Source/Target columns). |
| m9 | minor | `init` success output | Prints paths but no next step; best-in-class CLIs (`gh repo create`, `stripe`) end scaffolding with the next command. | Append: `Next: okfsmith ingest <source> <directory>` (e.g. `okfsmith ingest ./docs ./kb`). |
| m10 | minor | all commands | No EXAMPLES in any `--help` (compare `gh <cmd> --help`, `stripe <cmd> --help`). | Add 2–3 examples to the long help of `init`, `ingest`, `read`, `graph` via the command docstring, e.g. ingest: `Examples:\n  okfsmith ingest ./docs ./kb\n  okfsmith ingest report.pdf ./kb --no-llm`. |

**Deliberately not flagged:** the `'okfsmith.X' is not available on this branch yet` lazy-import errors — correct interim behavior for the cross-branch build (clear message, exit 1, no traceback); must not ship in the final release. `ingest` partial failure exiting 0 with a stderr warning is acceptable and documented; do not change without a `--fail-fast`/`--strict` decision from the coordinator.

## (3) Exemplar mockups — target state

### Mockup 1: `okfsmith ingest --help` (best-in-class help: examples, choices, grouped semantics)

```
Usage: okfsmith ingest [OPTIONS] SOURCE DIRECTORY

  Ingest documents into the bundle as draft concepts.

  Per-file SHA-256 is computed for every input. With --no-llm the
  deterministic sectioning path is used; otherwise LLM extraction runs
  (model selectable with --model).

  Examples:
    okfsmith ingest ./docs ./kb
    okfsmith ingest report.pdf ./kb --no-llm
    okfsmith ingest ./docs ./kb --recursive --model anthropic/claude-opus-4-6

╭─ Arguments ────────────────────────────────────────────────╮
│ *  source       File or directory to ingest. [required]    │
│ *  directory    Target OKF bundle directory. [required]    │
╰────────────────────────────────────────────────────────────╯
╭─ Options ──────────────────────────────────────────────────╮
│ --model <str>     Model for LLM extraction.                 │
│                   [default: provider default]               │
│ --no-llm          Use deterministic sectioning (no LLM).   │
│ --recursive       Recurse into subdirectories of SOURCE.   │
│ -q, --quiet       Suppress the progress bar (keep summary).│
│ --help            Show this message and exit.               │
╰────────────────────────────────────────────────────────────╯
```

### Mockup 2: conflicting flags + bad enum value (exit 2, actionable)

```
$ okfsmith ingest ./docs ./kb --no-llm --model gpt-5
error: --model has no effect with --no-llm (deterministic sectioning uses no model).
hint: drop --model, or drop --no-llm to use LLM extraction.
$ echo $?
2

$ okfsmith validate ./kb --format yaml
Usage: okfsmith validate [OPTIONS] DIRECTORY
Try 'okfsmith validate --help' for help.
╭─ Error ────────────────────────────────────────────────────╮
│ Invalid value for '--format': 'yaml' is not one of 'text',  │
│ 'json'.                                                    │
╰────────────────────────────────────────────────────────────╯
$ echo $?
2
```

### Mockup 3: `init --force` destructive guard + next-step close

```
$ okfsmith init ./kb --force
warning: --force will overwrite index.md and log.md in './kb'.
Scaffold anyway? [y/N]: y
Initialized OKF bundle in ./kb
  index: ./kb/index.md
  log:   ./kb/log.md

Next: ingest documents with
  okfsmith ingest <source> ./kb

$ okfsmith init ./kb --force --yes   # scripts: no prompt, warning still printed
```

### Mockup 4: ingest progress for long runs (rich, TTY-aware)

```
$ okfsmith ingest ./docs ./kb --recursive
⠋ Ingesting… ━━━━━━━━━━━━━━━━━╸━━━━━━ 7/12 files · 00:41 elapsed
✓ docs/quarterly-report.pdf            a91f…c204   14 concepts
✓ docs/notes.md                        77be…90aa    3 concepts
✗ docs/scanned-broken.pdf              01cd…44ef    failed: no extractable text (is this a scanned PDF? try --ocr when available)
…
Ingest summary — LLM extraction (model=default)
┏━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━┓
┃ File                     ┃ SHA-256  ┃ Concepts ┃ Status ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━┩
│ …                        │ …        │       14 │ ok     │
└──────────────────────────┴──────────┴──────────┴────────┘
Wrote 31 draft concept(s) to ./kb
warning: 1 of 12 input(s) failed (see above).
```

Notes: per-file failures name the file, say what failed, and suggest the fix — never a bare traceback. Progress auto-disables when piped; `--quiet` keeps only the table.

---

## Footer — supervision commitment

UX Panel A supervises **every** builder iteration on the CLI: after each builder pass touching `src/okfsmith/cli/`, we re-run the CLI, re-check every finding above (blocker → minor), and re-review until this panel returns **APPROVED**. No CLI change ships without a Panel A re-review sign-off.
