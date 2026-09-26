# Reviewer 1 — Round 0 baseline review (tools 1–8 of 40)

**Reviewer:** Reviewer 1 (benchmark set: `gh`, `git`, `docker`, `kubectl`, `terraform`, `ansible`, `aws-cli`, `azure-cli`)
**Date:** 2026-09-26 · **Branch scored:** `feat/cli` (CLI) + `master` scaffold/core · **Version:** 0.1.0 pre-integration
**Scope note:** Sibling slices (`okfsmith.parsers`, `.extract`, `.validate`, `.viz`, `.mcp_server`) land on other branches. `ingest`, `validate`, `graph --format html`, and `mcp` currently exit 1 with a clean "not available on this branch yet" message. Scores marked **provisional** where they depend on missing integration.

---

## 1. Per-tool notes — what each benchmark teaches (steal / avoid)

### github/gh
- **Command grammar:** `gh <resource> <verb>` (`gh pr create`) — discoverable, consistent. **Steal:** keep okfsmith's flat verb list (`init/ingest/validate/list/read/graph`) but audit every verb for single-responsibility.
- **Human-first output + explicit machine modes:** every list-type command supports `--json` with a documented stable schema; default output is human-readable. **Steal:** `--format json` (and `--quiet`) on `list` and `ingest`, with a schema contract.
- **Help leads with examples:** `gh <cmd> --help` shows usage examples before flag lists. **Steal:** add `Examples` sections to every Typer command help.
- **Auth done right:** tokens via `GH_TOKEN` env / `--with-token` from stdin — never via flags. okfsmith already does this (`ANTHROPIC_API_KEY` env-only). Keep.
- **Distribution:** single static binary, GitHub releases with checksums, package managers everywhere. **Steal the ambition:** `pip install okfsmith` + `uvx` must be the two-line story; publish early.

### git/git (the cautionary tale)
- **The anti-pattern:** `checkout`/`reset` each do a dozen unrelated things → 236-line help pages nobody can scan. okfsmith's `ingest` currently bundles *parse → section → extract → link → emit* in one command — **this is the checkout risk.** **Steal the fix:** git's porcelain/plumbing split → keep `ingest` as the friendly porcelain but make stages individually addressable (or at minimum `--dry-run` previews and per-stage `--only` flags) so help stays scannable.
- **Error messages** historically read like "src refspec master does not match any" (not even grammatical). okfsmith's errors (`error: source 'x' does not exist.`) are already plain-language — hold that bar everywhere.

### docker/cli
- **Progressive disclosure:** `docker run nginx` → `docker run -d -p 80:80 nginx` → `--cpus=".5"` — the simple case is trivially simple. **Steal:** `okfsmith ingest ./kb report.pdf` must work with zero flags (Tier 1 local, defaults everywhere). Currently it doesn't (see Gap #1).
- **Command groups in help output** (Management Commands vs Commands). **Steal** when the command list grows past ~8: group in `--help`.
- **`--format` templating** on `ps`/`images`. **Steal:** `--format` on `list`/`graph`.
- **Plugin architecture** (`docker buildx`). Relevant to Tier 2/3 parsers: keep the parser interface plugin-shaped.

### kubernetes/kubectl
- **Universal `-o json|yaml|wide|name`** on every read command. **Steal:** a global output-format convention, not per-command one-offs (`validate` has `--format`, `graph` has `--format`, `list` has *nothing* — inconsistent today).
- **`--dry-run=client`** and `kubectl diff` before apply. **Steal:** `okfsmith ingest --dry-run` + a `diff`-style preview of what would be written.
- **Weakness to avoid:** implicit context (`kubectl` acting on whatever kubeconfig points at, no visible reminder) causes prod accidents. okfsmith's explicit `./kb` directory argument is *better* — never introduce ambient bundle context without echoing it.

### hashicorp/terraform
- **Plan → confirm → apply** is the gold standard for consequential ops. **Steal:** `ingest` should print its plan (files → expected concepts) and, for destructive variants, confirm. `init --force` already follows this; extend the pattern.
- **Clear visual diffs** (`+`/`-`/`~`, with `-/+` for replacements). **Steal for** re-ingest/dedup output: show what changed, what merged.
- **Idempotency messaging** ("No changes. Your infrastructure matches the configuration."). **Steal:** `validate` already prints "Conformant: no errors, no warnings." — apply the same calm final line to every command.
- **Weakness to avoid:** plan output buries the one critical destroy among 800 tag updates; no risk ranking. For okfsmith: `validate` output should rank/sort errors before warnings, files alphabetically, never bury.

### ansible/ansible
- **Ad-hoc vs playbook split** (`ansible -m ping` vs `ansible-playbook`): one-offs vs repeatable runs. **Steal:** document which okfsmith commands are safe to re-run (idempotent) and which append/accumulate (`ingest` appends to log; say so in help).
- **`-v`/`-vv`/`-vvv` verbosity ladder** and `--check` mode. **Steal:** verbosity flags instead of chatty-by-default (git-push-style noise is the enemy); `--check` as synonym family with `--dry-run`.
- **Changed/ok/failed per-task recap** — the single most reassuring output pattern in automation CLIs. **Steal for** `ingest`: per-file recap table (already has one — keep and extend with a final recap line).
- **`ansible-doc` embedded docs**, always in sync with the installed version. **Steal:** docs generated from the code (`--help` as source of truth for the CLI reference table in README).

### aws/aws-cli
- **`--query` (JMESPath) + `--output json|text|table`** — the most complete output story in the industry. **Steal selectively:** `list --format json` now; consider `--query`-style filtering later (defer — don't gold-plate v0.1).
- **`--cli-input-json`** for complex inputs; **waiters** for long ops. **Steal:** long LLM extraction needs progress + a waiter-like poll, not silence (see Gap #6).
- **Structured error formats** (`--cli-error-format json`) added in v2 — machine-readable errors as a first-class feature. **Steal:** `validate --format json` already exists; extend to all commands' error paths.
- **Weakness to avoid:** `--output text` column order is *not contractually stable* — a trap okfsmith can avoid by versioning its JSON schemas from day one.

### azure/azure-cli
- **`az <noun> <verb>` consistency + a published `command_guidelines.md`** for contributors. **Steal both:** okfsmith needs a `docs/CONTRIBUTING-CLI.md`-style command authoring guide (verb conventions, flag conventions, error format) so 40+ contributors don't fragment the surface.
- **Consistent short flags** (`-g` resource group, `-n` name everywhere). **Steal:** reserve `-f/--force`, `-o/--output`, `-q/--quiet`, `-v/--verbose` with one meaning each, documented once.
- **`az find`** (in-terminal discoverability). Cheap version: make `okfsmith --help` and per-command `--help` genuinely sufficient; add a `topics` or `help <command>` alias later.

---

## 2. Baseline scores (0–10, decimals allowed)

| # | Dimension | Score | Provisional? | Justification |
|---|---|---|---|---|
| 1 | CLI UX | **6.0** | yes | Good bones: Typer, errors on stderr in plain language, exit codes, `--force` guard on `init`, lazy-slice errors that explain instead of tracebacking. But: the README's quickstart command (`okfsmith ingest ./kb docs/x.pdf`) does **not** match the implemented surface (`okfsmith ingest SOURCE --bundle KB`); `--bundle` flag vs positional directory is inconsistent across commands; `list`/`ingest` have no machine-readable output; no `--dry-run`; no examples in `--help`; no shell completion; no progress UX for long runs. |
| 2 | README quality | **7.5** | no | Excellent hook ("Forge messy documents…"), genuine 60-second quickstart, honest comparison table with a named "what we're not" section, skimmable with badges. Deductions: quickstart is aspirational (two commands 404 on this branch; ingest syntax contradicts the code); no CI/coverage badges; no demo screenshot or animated demo; no link to contributor docs; badge for PyPI points at a package not yet published. |
| 3 | Docs | **5.5** | no | `docs/OVERVIEW.md` is a genuinely good architecture document (8-stage pipeline, cross-cutting constraints). `examples/bundles/README.md` is solid. But docs stop there: no ingestion-tier guide, no LLM/Ollama configuration guide, no MCP setup guide, no troubleshooting, no API reference for `core/`, no CHANGELOG, no CONTRIBUTING. The README's CLI reference table is hand-maintained and already drifted from the code. |
| 4 | Packaging/distribution | **5.0** | no | Clean `pyproject.toml`: light runtime deps (`typer`, `pyyaml`, `rich`), sensible `mcp`/`ocr` extras, `src/` layout, Python ≥3.10 classifiers. Deductions: no `[project.urls]` (PyPI page will lack repo links); not yet published to PyPI (quickstart's `pip install okfsmith` fails today); no `.[dev]`/`.[test]`-complete extra (no ruff/mypy/pytest-cov); no lockfile or CI install check; `uvx` story mentioned once but untested. |
| 5 | Code quality | **6.5** | no | `core/` is clean: typed dataclasses, stdlib-only, docstrings with doctests, deterministic ordering, unknown-frontmatter-key preservation, single smoke-test file covering real behaviors (round-trip, trust tiers, index/log conventions). `cli/` is a thin, well-separated Typer layer with a thoughtful lazy-import pattern for not-yet-landed slices. Deductions: no linter/type-checker config (ruff/mypy absent); zero tests for the CLI layer; `.contract/` fixtures exist but aren't wired to any test; no coverage configuration or gates. |
| 6 | Demo/onboarding | **6.0** | yes | The 60-second quickstart *reads* beautifully and two realistic example bundles ship with a validating README (`okfsmith validate examples/bundles/cs-curriculum`). But time-to-first-success is currently **infinite** on this branch: `ingest` exits 1 ("not available on this branch yet"), so the core promise (PDF → bundle) can't be demoed. No sample messy input fixture, no `viz.html` screenshot, no recorded terminal demo, no `okfsmith demo`/tour command. |

**Mean: 6.08/10.** The project reads like a 7.5 and runs like a 5.5 — the gap is integration, output contracts, and contributor scaffolding, not vision.

---

## 3. TOP 10 ACTIONABLE GAPS (ranked by impact)

### G1. Quickstart command contradicts the implementation — fix the surface, then the docs
- **Gap:** README says `okfsmith ingest ./kb docs/quarterly-report.pdf`; the CLI implements `okfsmith ingest SOURCE --bundle ./kb`. A first-time user copy-pasting the quickstart gets `Error: No such file or directory: './kb'`-style confusion (worse: silent misparse).
- **Evidence:** `README.md` "60-second quickstart" + "CLI reference" table vs `commands.py::ingest(source: Path = typer.Argument(...), bundle: Path = typer.Option(..., "--bundle"))`.
- **Proposed fix:** Standardize on positional bundle first — `okfsmith ingest ./kb <source>…` — matching `init/validate/list/read/graph` (all take the bundle as a positional). Keep `--bundle` as a deprecated alias for one minor version if anything already uses it. Update README, `--help`, and add a CLI contract test asserting README's quickstart commands parse.
- **Effort:** S

### G2. No machine-readable output contract on read-path commands
- **Gap:** `validate` has `--format json`, `graph` has `--format json`, but `list` (the most scriptable command) and `ingest`'s summary have no machine-readable mode. gh/kubectl/aws-cli all guarantee `--json` on every list-type command.
- **Evidence:** `commands.py::list_concepts` — table only; `ingest` — rich table to stdout with no `--quiet`/`--format`.
- **Proposed fix:** Add `--format text|json` (default `text`) to `list`, `ingest` summary, and `read`; define the JSON schemas in `docs/` and freeze them (semver the schema, per the aws-cli `text`-instability lesson). Add `--quiet` (errors only) for scripting.
- **Effort:** M

### G3. No `--dry-run` / `--check` preview for ingest
- **Gap:** The most consequential command (LLM extraction writes files, appends to log, mutates index) has no preview. terraform's `plan`, ansible's `--check`, kubectl's `--dry-run=client` all exist because consequential CLIs need them.
- **Evidence:** `ingest` writes concepts immediately; no flag to preview.
- **Proposed fix:** `okfsmith ingest ./kb src --dry-run` prints the per-file plan (files found, SHA-256, expected target paths, tier/model that would run) and exits 0 without writing. Reuse the existing ingest summary table with a "DRY RUN" banner.
- **Effort:** M

### G4. Integration: 4 of 7 commands are stubs on this branch — the quickstart cannot succeed
- **Gap:** `ingest` (LLM path), `validate`, `graph --format html`, `mcp` all depend on unlanded slices. The README's headline flow is unrunnable; Demo/onboarding is scored on a promise.
- **Evidence:** `_lazy_attr` exits 1 for `okfsmith.parsers`, `.extract`, `.validate`, `.viz`, `.mcp_server` on `feat/cli`.
- **Proposed fix:** (Builder + coordinator) land slices, then add one end-to-end integration test that executes the README quickstart verbatim (`init` → `ingest` sample fixture → `validate` → `list`) in a tmp dir and asserts exit 0. This test is the release gate for v0.1.0.
- **Effort:** L *(blocked on sibling branches, not builder-only — flagged for coordinator)*

### G5. No shell completion; `--help` has no examples
- **Gap:** `add_completion=False` is set explicitly, and no command help shows an example. clig.dev, gh, docker, kubectl all treat examples-in-help and completion as table stakes.
- **Evidence:** `app.py` (`add_completion=False`); all command docstrings are one-liners with no `Examples:` section.
- **Proposed fix:** Enable Typer completion; add an `Examples:` block to each command's help (2–3 copy-pasteable invocations). Generate the README's CLI reference table from `--help` output in CI to prevent G1-style drift.
- **Effort:** S

### G6. Long operations are silent — no progress UX
- **Gap:** LLM extraction over a 200-page PDF will run for minutes with zero output; the existing per-file table only renders at the end. `rich` (already a dependency) has `Progress`; aws-cli's waiters and terraform's live plan output exist for exactly this.
- **Evidence:** `ingest` loop prints the summary table only after all files complete; failures surface as bare `failed: {exc}`.
- **Proposed fix:** Wrap the ingest loop in `rich.progress` (per-file spinner + overall bar), stream per-file status lines to stderr, keep the final table. Add `--quiet` (G2) to suppress for CI. Never print raw tracebacks without `--verbose` (add `-v` ladder later, ansible-style).
- **Effort:** S

### G7. Packaging: missing PyPI metadata, unpublished package, no dev tooling
- **Gap:** No `[project.urls]`, no published release, no `.[dev]` extra (ruff/mypy/pytest-cov), no CI workflow. The README's install story (`pip install okfsmith`, badges) points at nothing shippable.
- **Evidence:** `pyproject.toml` (no `[project.urls]`, no lint/type config); no `.github/workflows/`; PyPI name verified free but unclaimed.
- **Proposed fix:** Add `[project.urls]` (Homepage, Repository, Issues, Changelog); publish `0.1.0a1` to PyPI/TestPyPI; add `dev = ["ruff", "mypy", "pytest", "pytest-cov"]` extra + `ruff`/`mypy` config; add CI (install matrix py3.10–3.12, `pytest`, `ruff check`, contract-fixture validation).
- **Effort:** M

### G8. Docs: guides, API reference, and contributor contract are missing
- **Gap:** After OVERVIEW.md there's a cliff: no ingestion-tier guide, no Ollama/LLM config guide, no MCP consumer guide, no troubleshooting, no `core/` API reference, no CHANGELOG, no CONTRIBUTING. azure-cli's `command_guidelines.md` shows the value of a contributorfacing CLI contract for a 40+-person team.
- **Evidence:** `docs/` contains only `OVERVIEW.md`; no `CONTRIBUTING.md`, `CHANGELOG.md` at repo root.
- **Proposed fix:** Add `docs/guides/` (ingestion-tiers, llm-config, mcp-serving, troubleshooting), generate API reference from docstrings (mkdocstrings/pdoc), add `CONTRIBUTING.md` + `docs/cli-authoring-guide.md` (verb/flag/error conventions per G2/G3/G5), start `CHANGELOG.md` (Keep a Changelog format).
- **Effort:** M

### G9. Demo gap: nothing to see, nothing to ingest
- **Gap:** No sample messy input (a small PDF/markdown fixture), no `viz.html` screenshot or animated demo in the README, no tour. kubectl/terraform READMEs convert with animated demos; okfsmith's graph feature is invisible.
- **Evidence:** `examples/` has output bundles only; README has no images/GIFs.
- **Proposed fix:** Add `examples/inputs/` (one small messy PDF + one markdown file, license-clean); screenshot `viz.html` into README; record a 60-second terminal demo (asciinema/vhs) of init→ingest→validate→graph; consider `okfsmith demo` that scaffolds a tour bundle. (Honest-placeholder rule applies: demo content must be obviously synthetic.)
- **Effort:** M

### G10. Zero CLI-layer tests; contract fixtures unwired
- **Gap:** One smoke-test file covers `core/` only. The CLI layer (argument parsing, exit codes, stdout/stderr separation, error messages) is untested, and the rich `.contract/fixtures/` corpus (valid bundles, 8 error/warning cases, EXPECTED.json) has no test harness.
- **Evidence:** `tests/` = `test_core_smoke.py` only; `.contract/fixtures/*/EXPECTED.json` unreferenced by any test.
- **Proposed fix:** Add `tests/test_cli.py` using Typer's `CliRunner`: cover `init` (incl. `--force` refusal), `list --format json` (G2), `read` missing-concept exit code, stderr/stdout separation, and run every `.contract/fixtures/*` case through `validate` asserting exit codes and EXPECTED.json. Gate merges on this suite (ties to G7 CI).
- **Effort:** M

---

## 4. Footer — loop rules

- **Re-score protocol:** On re-invocation I will re-run this rubric against the new tree, re-verify each gap's evidence (especially G1's README↔code consistency and G4's quickstart E2E), and update scores with a round-over-round delta table.
- **Plateau rule:** If total mean score does not improve for 2 consecutive rounds, I stop and name the blocker honestly.
- **What blocks 10/10 today (honest):** (a) **G4** — sibling slices (`parsers`, `extract`, `validate`, `viz`, `mcp_server`) are on other branches; CLI UX and Demo cannot exceed ~7 until the quickstart runs end-to-end. (b) **No PyPI release** — Packaging cannot exceed ~7 until `pip install okfsmith` works. (c) **Real LLM extraction quality** — the extraction pipeline's output quality (the product's actual value proposition) cannot be scored from scaffolding; needs a real model run over the sample fixture. These three are integration/release realities, not builder effort — the builder should not be penalized for them, but they cap the ceiling.
- **Highest-leverage builder work for Round 1:** G1 (S), G5 (S), G6 (S), G2 (M), G10 (M) — all builder-owned, no cross-branch dependencies, and they move CLI UX + Code quality + Demo the fastest.

*Report saved to `~/workspace/projects/okfsmith/.contract/reviews/r1-reviewer-1.md` per deliverable path. Read-only elsewhere; no commits, no pushes.*
