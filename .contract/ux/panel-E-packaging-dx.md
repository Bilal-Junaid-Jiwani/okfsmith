# UX Panel E — Demo & Packaging DX Verdict

**Panel:** E (3 senior DX/packaging designers, one voice)
**Date:** 2026-09-26 · **Scope:** install story, first-run, MCP client docs, extras design, version/help consistency, uninstall
**Judged against:** `uv`/`uvx`, `pipx`, `ruff`, `stripe-cli` install DX
**Read-only audit:** no commits, no pushes. Verified by executing the installed build (`okfsmith 0.1.0`, editable install of the main repo tree).

---

## (1) VERDICT: **CHANGES-REQUIRED**

The packaging *metadata* is sound — src layout, lean base deps (`typer`, `pyyaml`, `rich`), correctly-optional `fastmcp`, console script `okfsmith`, `requires-python >=3.10`, Apache-2.0 LICENSE shipped in the dist. That is the good news, and it is the only part of the install story that currently works.

Everything a new user touches in the first five minutes is broken or fictional:

- **Every command in the README quickstart fails.** `init`, `ingest`, `validate`, `list`, `read`, `graph`, `mcp` → `No such command '<name>'`, exit 2. The CLI (`src/okfsmith/cli/app.py`) implements only `--version`. The 60-second quickstart, the CLI reference table, and `docs/OVERVIEW.md` describe a product that does not exist in this tree.
- **`pip install okfsmith` 404s.** PyPI name is free but unpublished (verified `https://pypi.org/pypi/okfsmith/json` → 404 on 2026-09-26). Quickstart line 1 fails; the PyPI and license shields link to 404 pages; `uvx okfsmith …` also 404s because `uvx` always resolves from PyPI and ignores the local install.
- **`uvx okfsmith mcp --bundle ./kb` cannot work three ways:** no `mcp` subcommand; the `mcp_server` package exists only in the `/tmp/wt-mcp` worktree, not in the main repo tree — so `pip install "okfsmith[mcp]"` from the main tree installs `fastmcp` but no `okfsmith.mcp_server` module (a raw `ModuleNotFoundError`, not the friendly `RuntimeError`); and the GitHub repo the README's Development section clones (`github.com/Bilal-Junaid-Jiwani/okfsmith`) also 404s.
- **MCP client docs are a single generic JSON block.** No per-client configs for Copilot or Gemini, a relative `./kb` bundle path (MCP servers launch with an unpredictable cwd — this silently breaks), no `uv ≥ 0.7.0` note for the `uvx "okfsmith[mcp]"` form, no guidance for pip/pipx-installed users.

This panel does not grade effort or architecture — only what a stranger experiences in their terminal. Best-in-class or nothing: **nothing ships to a user until every line of the quickstart runs green in CI.**

---

## (2) Findings

Severity: **B** = blocker (ship-stopper) · **H** = high · **M** = medium.

| # | Sev | Area | Issue | Concrete fix spec |
|---|---|------|-------|-------------------|
| 1 | B | First-run / docs-vs-reality | README quickstart, CLI reference table, and `docs/OVERVIEW.md` document 7 commands (`init ingest validate list read graph mcp`); CLI implements **zero**. Verified: each returns `No such command`, exit 2. | (a) Implement the commands (CLI engineer's scope). (b) Add a CI job `docs-smoke` that extracts every `okfsmith …` command line from `README.md` quickstart and runs it against `.contract/fixtures/valid/` in a temp dir; fail the build if any documented command errors. Docs must never again describe vapor. |
| 2 | B | Install story | `pip install okfsmith` → 404 (PyPI unpublished). Badges link to 404 pages. `uvx okfsmith …` → 404 for the same reason. The Development section's `git clone https://github.com/Bilal-Junaid-Jiwani/okfsmith` → 404 (repo does not exist yet). | Publish `0.1.0` to PyPI **before** the quickstart keeps its `pip install okfsmith` line, or until then replace the install step with a clearly-labeled pre-release path and create the GitHub repo. Gate: CI asserts `pip index versions okfsmith` (or the PyPI JSON API) returns 200 and the published version matches `src/okfsmith/__init__.py::__version__`. |
| 3 | B | MCP serve path | `uvx okfsmith mcp --bundle ./kb` triple-broken: (i) no `mcp` subcommand; (ii) `okfsmith.mcp_server` absent from the main tree (only in `/tmp/wt-mcp`) — `pip install "okfsmith[mcp]"` installs fastmcp but the import `okfsmith.mcp_server` raises `ModuleNotFoundError`, bypassing the designed friendly `RuntimeError`; (iii) no published package for `uvx` to fetch. | Merge `mcp_server/` into the main `src/okfsmith/` tree. Add CI test: build sdist → install into a clean venv **without** the extra → assert `okfsmith mcp --bundle <fixture>` prints the friendly install hint (not a traceback); install **with** `[mcp]` → assert the stdio server starts and answers `index()`. |
| 4 | B | MCP client setup docs | `mcp_server/README.md` gives one generic JSON block: `"command": "uvx", "args": ["okfsmith[mcp]", "mcp", "--bundle", "<path-to-your-bundle>"]`. Problems: no Copilot config, no Gemini config; relative bundle path breaks under MCP hosts (unknown cwd); no note that `uvx "pkg[extra]"` requires uv ≥ 0.7.0; nothing for pip users (`okfsmith` on PATH) beyond a passing mention; nothing for pipx users (`pipx inject okfsmith "okfsmith[mcp]"` or `pipx install "okfsmith[mcp]"`). | Rewrite the Client configuration section with four copy-pasteable blocks, each with an **absolute** bundle path: **Claude Code** (`~/.claude.json`), **Cursor** (settings → MCP), **VS Code / Copilot** (`.vscode/mcp.json`, `"type": "stdio"`), **Gemini CLI** (`~/.muse/settings.json` → `mcpServers`). Keep the `uvx` form but add: *"requires uv ≥ 0.7.0 for the `[mcp]` extra form; quote the package spec in shells."* Add pipx line: `pipx install "okfsmith[mcp]"`. CI: validate every JSON block with `python -m json.tool`. |
| 5 | H | First-run (bare invocation) | Bare `okfsmith` → `Usage: … / Missing command.` exit 2. `ruff`, `uv`, `stripe-cli` all print help on bare invocation. A new user's literal first run is an error panel. | Set `no_args_is_help=True` on the Typer app (or equivalent callback handling). Bare `okfsmith` prints full `--help` and exits 0, ending with a first-run hint line, e.g. `New here? Run 'okfsmith init ./kb' to start a bundle, or 'okfsmith --help'.` |
| 6 | H | Graceful failure paths | Failure UX is unspecified and currently hostile: `serve()` raises a raw `FileNotFoundError` traceback for a missing `--bundle` path; there is no defined behavior for `init` into a non-empty dir, `ingest` of a missing/unreadable file, or no-Ollama when LLM extraction is requested. | CLI must catch all expected failures and render: one line of cause + one line of fix, exit non-zero, no traceback. Concrete specs: `okfsmith mcp --bundle /nope` → `Error: bundle not found: /nope` + `Run 'okfsmith init /nope' to create one, or pass an existing bundle path.`; `init` into non-empty dir → refuse unless `--force`, and say so; `ingest` with no Ollama reachable and no hosted key → `No local model found. Start Ollama (ollama serve) or set OKFSMITH_MODEL / ANTHROPIC_API_KEY — see Configuration.` Every error path gets a test asserting exit code and message, no traceback. |
| 7 | H | PyPI metadata | `[project]` has no `[project.urls]` — `pip show` reports an empty Home-page; the PyPI page (once published) will look abandoned. `authors` has a name but no email. | Add `[project.urls]`: `Homepage`, `Repository`, `Documentation`, `Changelog` pointing at the (to-be-created) GitHub repo. Add author email. |
| 8 | H | Dev-install docs | README Development says `pip install -e .` then `pytest` — but `pytest` only comes via the `test` extra, so a fresh contributor gets `pytest: command not found`. | Change to `pip install -e ".[test]"`. CI: run the Development section's commands verbatim in a clean container. |
| 9 | M | Extras design (keep) | Base deps are lean (`typer`, `pyyaml`, `rich`) ✓; `fastmcp` is correctly optional with a lazy import and a genuinely helpful `RuntimeError` ✓. `ocr = ["docling"]` is unpinned and docling is a very heavy install — users will be surprised. | Keep the design. Add a lower bound (`docling>=2`) and one line in the README extras note with the approximate installed size / install time of `[ocr]` so users can decide. |
| 10 | M | Version consistency | `--version` prints `okfsmith 0.1.0` and matches `pyproject.toml` today, but `__version__` is hardcoded in `__init__.py`, duplicating the `version` field — they will drift. | Single-source it: read the version from installed metadata (`importlib.metadata.version("okfsmith")`) with a fallback to the hardcoded string for uninstalled source checkouts. Add a CI check that the two agree when installed. |
| 11 | M | Uninstall cleanliness | By construction clean (one console script, no data dirs, no post-install hooks) — but untested, and `init`/`ingest` don't exist yet to prove they write only inside the bundle dir. | Add CI job: `pip install` → run quickstart → `pip uninstall -y okfsmith` → assert `which okfsmith` is empty and `pip show -f okfsmith` fails. Contract: okfsmith must never write outside the bundle path and `$TMPDIR` except standard caches; document that `pipx`/`uvx` users leave only their tool's own cache. |
| 12 | M | Help discoverability | `okfsmith --help` currently lists zero commands; once commands land, help is the discovery surface. | When commands exist: group them in help output (`Bundle`, `Knowledge`, `Serve`) via Typer rich-help panels; every command and option gets a one-line help string; `okfsmith <cmd> --help` shows examples. CI: assert `--help` output mentions all documented commands. |

**What is already right (do not regress):** src layout with `packages.find where = ["src"]` ✓; `requires-python >=3.10` ✓ (and `bool | None` annotations are 3.10-safe); Apache-2.0 `LICENSE` present and shipped in the wheel dist-info ✓; `add_completion=False` (no shell-completion spam on install) ✓; MCP tools return `Error: …` strings instead of raising ✓; bundle loaded once at server startup ✓; read-only tools ✓; no secrets in flags/files (env-only keys) ✓.

---

## (3) The ideal first-5-minutes terminal transcript

This is the bar. The builder makes **every line below real**, verbatim behavior, and the CI `docs-smoke` job runs it.

```console
$ pip install okfsmith
Successfully installed okfsmith-0.1.0

$ okfsmith
Usage: okfsmith [OPTIONS] COMMAND [ARGS]...

  Convert messy documents into OKF v0.2 knowledge bundles.

Commands:
  init      Scaffold a new OKF v0.2 bundle
  ingest    Parse sources → extract concepts → link → emit
  validate  Check OKF §11 conformance (hard rules + advisory lints)
  list      List concepts in the bundle
  read      Print a concept with its frontmatter
  graph     Render viz.html for the concept graph
  mcp       Serve the bundle over MCP (stdio)

New here? Run 'okfsmith init ./kb' to start a bundle.

$ okfsmith init ./kb
✓ Created bundle at ./kb
  index.md   bundle map (edit me)
  log.md     provenance log (append-only)

$ okfsmith ingest ./kb docs/quarterly-report.pdf
  parse    ▸ Tier 1 (local, free): 212 pages → clean text
  section  ▸ 34 sections
  extract  ▸ No local model found. Start Ollama ('ollama serve')
             or set OKFSMITH_MODEL / ANTHROPIC_API_KEY — see 'Configuration'.
             Nothing was written. Run again when ready.

$ ollama serve &>/dev/null &   # user starts Ollama (their step, not ours)

$ okfsmith ingest ./kb docs/quarterly-report.pdf
  parse    ▸ Tier 1 (local, free): 212 pages → clean text
  section  ▸ 34 sections
  extract  ▸ 2-pass (draft + critic): 42 concepts
  link     ▸ 118 relations
  emit     ▸ wrote 42 concepts + index.md
✓ Bundle ready at ./kb

$ okfsmith validate ./kb
42 concepts · 0 errors · 3 warnings
  warn  concepts/opex.md: no description (recommended field)
  warn  concepts/capex.md: link to 'finance/tax' not found (spec §6: warning, not error)
  warn  concepts/headcount.md: stub (body < 50 chars)

$ okfsmith mcp --bundle ./kb
Error: the MCP server needs the 'mcp' extra.
  pip install "okfsmith[mcp]"      (pip)
  pipx install "okfsmith[mcp]"     (pipx)
  # then: uvx "okfsmith[mcp]" mcp --bundle "$PWD/kb"   (no install, needs uv ≥ 0.7.0)

$ pip install "okfsmith[mcp]"
Successfully installed okfsmith-0.1.0 fastmcp-2.x

$ uvx "okfsmith[mcp]" mcp --bundle "$PWD/kb"
  okfsmith MCP server · bundle: /home/user/kb (42 concepts)
  tools: index, list, search, get, neighbors · transport: stdio
  (waiting for MCP client…)

$ okfsmith --version
okfsmith 0.1.0

$ pip uninstall -y okfsmith
Successfully uninstalled okfsmith-0.1.0
$ which okfsmith
okfsmith not found
```

Notes on the transcript: `ingest` without Ollama must fail **before writing anything**, with the fix on the next line. The `mcp` missing-extra error must name all three installers (pip / pipx / uvx), not just pip. The `uvx` form quotes the extra and uses an absolute bundle path. `validate` prints the `N concepts · E errors · W warnings` summary first, details after. Uninstall leaves nothing behind.

---

## Footer — supervision

Panel E supervises **every** builder iteration on demo & packaging DX. We will re-review after each iteration and we will not approve until: every command in the README runs as documented (CI `docs-smoke` green), `pip install okfsmith` and `uvx "okfsmith[mcp]" mcp --bundle <abs-path>` work against the real PyPI/GitHub remotes, all four MCP client configs are present and JSON-valid, bare `okfsmith` prints help, every first-run failure path exits non-zero with cause + fix and no traceback, and the uninstall check is clean. Iterate until **APPROVED** — best-in-class or nothing.
