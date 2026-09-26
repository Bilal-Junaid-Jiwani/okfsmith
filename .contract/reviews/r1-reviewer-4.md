# Reviewer 4 — Round 1 (2026-09-26)

**Reviewer:** okfsmith senior team, Reviewer 4 of 5
**Benchmark set:** lazygit, gitui, k9s, helm, gum, glow, just, navi
**Baseline under review:** master @ `4a49853` (scaffold + core lib + README + docs/OVERVIEW.md
+ examples/bundles + .contract fixtures) plus CLI implementation on `/tmp/wt-cli` branch
`feat/cli` (`app.py`, `commands.py`, 7 Typer commands). No commits made — read-only review.
Sibling slices (parsers, extract, validate, viz, mcp_server) are **not integrated**; commands
that need them fail cleanly with "not available on this branch yet". Scores marked
**[provisional]** where integration is pending.

Method: web search + GitHub README of each benchmark tool, focused on TUI/interactive UX,
rich terminal output, keybinding/discoverability, and demo quality.

---

## 1. Per-tool pattern notes — what to steal

### lazygit (jesseduffield/lazygit, ~80k★) — the TUI discoverability king
- **Steal:** the `?` keybinding overlay — every screen answers "what can I press here?"
  without leaving the app. A demo GIF *above the fold* in the README. The rant-style
  "Rant time" motivation section: it names the pain before pitching the tool.
  Enormous install matrix (brew, scoop, conda, go, distro packages, manual).
- **Weakness to avoid:** performance collapses on huge repos (gitui's benchmark shows
  57s / 2.6GB vs gitui's 24s / 0.17GB on the Linux kernel repo). For okfsmith: the
  ingest path must stay responsive on 200-page PDFs — never let parsing block the UI thread.

### gitui (extrawurst/gitui) — speed as a feature, honesty as a brand
- **Steal:** context-sensitive help bar — "no need to memorize tons of hot-keys" is the
  tagline. The **benchmark table in the README** (time/memory/binary/freezes/crashes)
  as social proof. Async git API so the UI never blocks — design goal stated explicitly.
  A "Limitations" section (gpg signing shortcomings) that builds trust.
- **Weakness to avoid:** contributor friction (Rust toolchain); documented but real.
  For okfsmith: keep the contributor path `pip install -e . && pytest`.

### k9s (derailed/k9s) — power-user UX: command mode, plugins, skins
- **Steal:** vim-style command mode (`:pods`, `:deploy`) — a command palette is the
  fastest discoverability surface. `plugins.yaml` extensibility and `skins/` theming.
  XRay (tree view) and Pulses (health dashboard) — rich structured views, not just lists.
  Dedicated docs site (k9scli.io) with `k9s info` as the "does it work?" check.
- **Weakness to avoid:** config sprawl (aliases.yaml, plugins.yaml, skins/) overwhelms
  newcomers. For okfsmith: zero-config default first, config files later.

### helm (helm/helm, CNCF) — distribution done at planetary scale
- **Steal:** the one-line install script (`get-helm-3 | bash`), `helm version` as the
  smoke test, a published **cheatsheet** (helm.sh/docs/intro/cheatsheet/), `helm search`
  for discoverability of the artifact catalog, OCI-registry distribution, and release
  signing/provenance. Docs live on a versioned site, README stays lean.
- **Weakness to avoid:** README alone doesn't teach you helm — it depends on the docs
  site existing. For okfsmith pre-1.0: the README must be self-sufficient until a docs
  site exists.

### gum (charmbracelet/gum) — composable interactive primitives
- **Steal:** every component is a command with self-documenting flags
  (`gum choose`, `gum confirm`, `gum spin`, `gum table`, `gum format`) — discoverability
  *is* the CLI surface. The README **tutorial** (Conventional Commits walkthrough)
  teaches by building something real. **VHS terminal recordings** for demo GIFs —
  scripted, reproducible, version-controlled demos. Each command prints to stdout →
  Unix-pipeline friendly.
- **Weakness to avoid:** components don't compose interactively without a script.
  For okfsmith: `gum confirm` pattern for destructive ops; `gum spin` pattern for
  long LLM passes.

### glow (charmbracelet/glow) — TUI + CLI dual mode, zero learning curve
- **Steal:** bare `glow` opens the browser TUI; `glow file.md` renders one file —
  the **same binary serves interactive and scripted use**. Reads from file, stdin,
  URL, and GitHub shorthand. Auto-detects terminal background (dark/light).
  `less`-compatible keystrokes + `?` for the full hotkey list.
- **Weakness to avoid:** the stash feature is niche cruft. For okfsmith: `okfsmith read`
  is the glow analog — it should render concepts beautifully (rich markdown), and a
  future `okfsmith browse` TUI would be the bare-`glow` analog.

### just (casey/just, ~35k★) — errors and discoverability as UX
- **Steal:** `just --list` — recipes are discoverable from the command line.
  **Shell completion for every major shell**, shipped and documented. Errors carry
  *source context* (file, line, snippet). Static validation before anything runs
  (unknown recipe → immediate, clear error). Runs from any subdirectory.
  The README *is also a book* (just.systems/man) — one source, two depths.
- **Weakness to avoid:** the README is book-length; newcomers bounce. For okfsmith:
  keep README tight, push depth into docs/ pages (the navi model).

### navi (denisidoro/navi) — the cheatsheet as onboarding
- **Steal:** an **asciinema demo at the very top** of the README — 10 seconds beats
  10 paragraphs. Fuzzy-searchable cheatsheets: the tool teaches you the commands
  *while you use it*. `--best-match` non-interactive mode for scripts. Shell widget
  (Ctrl+G) meets users where they type. **Repology badge** showing every distro
  package — packaging status as a live badge. `docs/` split into per-topic pages.
- **Weakness to avoid:** hard dependency on fzf/skim. For okfsmith: no mandatory
  external interactive dependency; keep the TUI optional.

**Cross-cutting steal list:** demo GIF/asciinema above the fold (lazygit, navi, gum/VHS);
`?`-style in-app help (lazygit, glow); context-sensitive help bar (gitui); shell
completion (just); benchmark/honesty tables (gitui, lazygit rant); one-line install +
cheatsheet (helm); tutorial that builds something real (gum); docs/ per-topic pages
(navi); read-from-stdin/URL flexibility (glow); repology-style packaging visibility (navi).

---

## 2. Baseline scores (round 1)

| # | Dimension | Score | Justification |
|---|---|---|---|
| 1 | CLI UX | **6.0** | Solid Typer + rich foundation: clean `error: …` messages on stderr with exit 1, `--version`, per-command `--help`, text/json `--format` on validate/graph, and graceful "not available on this branch yet" for unintegrated slices. But `add_completion=False` explicitly kills shell completion (just's #1 steal), there is zero progress UI for long-running ingest (rich `Progress` imported nowhere), no interactive confirmation before destructive `--force init`, no `--quiet`/`--verbose` levels, no `NO_COLOR` respect, and `list` lacks `--format json`. **README documents `okfsmith ingest ./kb <src>` but the CLI takes `okfsmith ingest <src> --bundle ./kb`** — the flagship quickstart command contradicts the implementation. |
| 2 | README quality | **7.0** | Landing-page structure, 60-second quickstart, badges, "Why okfsmith" gap table, an explicit honest-comparison section, config table, and a roadmap with named non-goals — unusually honest for a pre-1.0 project. Gaps: **no visual demo** (every benchmark has GIF/asciinema above the fold), the ingest quickstart syntax is factually wrong (see above), badges point at a PyPI page that 404s (package not published), no install troubleshooting, no shell-completion mention. |
| 3 | Docs | **4.5** | Only `README.md` + `docs/OVERVIEW.md` (an excellent architecture pipeline doc). No per-command reference pages (navi model), no tutorial walkthrough beyond the 60-sec quickstart (gum model), no CHANGELOG, no CONTRIBUTING, no man pages, no cheatsheet, no docs site. Command help strings are minimal one-liners. |
| 4 | Packaging/distribution | **3.5** | `pyproject.toml` is clean: src layout, console script, `mcp`/`ocr`/`test` extras, `>=3.10`, real classifiers. But: **not on PyPI yet** (roadmap admits "first PyPI release"; badges are aspirational), no `.github/` CI or release workflow, no trusted-publisher setup, no `uvx`/`pipx` verification, no standalone binary story, no Homebrew/conda path, no signing/SBOM. helm's one-line install and navi's repology visibility are the targets. **[provisional]** — publish pipeline is explicitly planned. |
| 5 | Code quality | **7.0** | Thin-Typer-over-core separation is real, lazy imports with helpful errors (not tracebacks), typed signatures, docstrings, env-only secrets, SHA-256 per-file ingest table with per-file failure isolation. But: only one smoke test file on master, no lint config (ruff), no type-check config (mypy), no CI to enforce anything, and the graded artifact (`commands.py`) lives on an unmerged branch. **[provisional]** — re-score after Wave-2 integration lands. |
| 6 | Demo/onboarding | **4.0** | Textual quickstart + two real example bundles (`okf-primer`, `cs-curriculum`) are genuine onboarding assets, and `viz.html` gives a human-readable payoff. But: no recorded demo (VHS/asciinema), no screenshots, no `okfsmith demo` self-guided tour, no sample input document to ingest, and the golden path `init → ingest → validate` requires an LLM (Ollama) or the not-yet-integrated parsers slice — a new user cannot complete the quickstart today. **[provisional]** |

**Round-1 average: 5.3 / 10.** Strongest: README honesty and CLI error hygiene. Weakest:
packaging (unpublished), docs depth, and demo (text-only).

---

## 3. Top 10 actionable gaps for the builder (ranked by impact)

**1. Publish to PyPI + add CI/release workflow** — Effort: M
- Gap: badges link to a PyPI page that 404s; `pip install okfsmith` fails; no `.github/` workflows.
- Evidence: roadmap lists "first PyPI release" as future; `pyproject.toml` is publish-ready but unpublished.
- Fix: GitHub Actions CI (pytest on 3.10–3.12, ruff, mypy) + PyPI trusted-publisher release on tags; smoke-test `pip install` and `uvx okfsmith --version` from a clean container before announcing.

**2. Fix the README↔CLI ingest mismatch; re-enable shell completion** — Effort: S
- Gap: README quickstart shows `okfsmith ingest ./kb docs/quarterly-report.pdf`; the CLI requires `okfsmith ingest <source> --bundle ./kb`. Also `app.py` sets `add_completion=False`, deleting free Typer completion (just's signature steal).
- Evidence: `commands.py` (`ingest` signature) vs `README.md` quickstart + CLI reference table.
- Fix: correct README to the real syntax (or change the CLI to match the README — decide once, document once); remove `add_completion=False` and document completion install for bash/zsh/fish.

**3. Ship a visual demo (VHS/asciinema) at the top of the README** — Effort: M
- Gap: zero visual media; all 8 benchmarks open with GIF/asciinema.
- Evidence: README has no images; gum's repo shows VHS gives scripted, reproducible terminal recordings.
- Fix: write `demo/vhs/demo.tape` running the golden path (`init` → `ingest --no-llm` on a sample doc → `validate` → `graph`), render GIF, embed above the fold; re-record on UX changes.

**4. Progress UX for long-running commands (rich Progress / spinners)** — Effort: M
- Gap: `ingest` loops over files and LLM passes with no feedback; a 200-page PDF looks hung (lazygit's failure mode, gitui's design goal).
- Evidence: `commands.py::ingest` prints only a final table; rich is already a dependency but `Progress` is unused.
- Fix: `rich.progress` for per-file ingest + `status` spinners around LLM passes; `--quiet` for scripts/CI; keep the final summary table.

**5. Interactive confirmation for destructive operations** — Effort: S
- Gap: `init --force` scaffolds into a non-empty directory with no prompt (gum's `confirm` pattern exists for exactly this).
- Evidence: `commands.py::init` — `--force` proceeds silently.
- Fix: prompt `Directory not empty — scaffold anyway? [y/N]` unless `--force` is paired with `--yes`/`-y` (CI-safe); never prompt when stdout is not a TTY.

**6. Expand docs/: per-command reference + tutorial + CHANGELOG + CONTRIBUTING** — Effort: M
- Gap: docs/ is a single architecture file; no command reference, no end-to-end tutorial, no changelog, no contributor guide (navi's per-topic docs/, just's book).
- Evidence: `docs/` contains only `OVERVIEW.md`; repo has no `CHANGELOG.md`/`CONTRIBUTING.md`.
- Fix: `docs/commands/<cmd>.md` generated from `--help` (CI-checked for drift); `docs/tutorial.md` walking a real sample bundle; `CHANGELOG.md` (keep-a-changelog); `CONTRIBUTING.md` (conventional commits, tests-required, no-secrets rule already in BUILD_LOG).

**7. Command discoverability: grouped help + friendlier errors** — Effort: S–M
- Gap: flat command list; unknown commands produce Typer's terse error with no suggestions; no `just --list` equivalent.
- Evidence: `app.py` registers commands with no help groups; no "did you mean?" handling.
- Fix: rich help panels grouping pipeline commands (`init`, `ingest`) vs inspection (`list`, `read`, `graph`, `validate`) vs serving (`mcp`); add `okfsmith --help` examples section; consider `no_args_is_help`.

**8. Respect NO_COLOR / add --format to `list` and `read`** — Effort: S
- Gap: `validate`/`graph` have `--format`, `list`/`read` don't; color output can't be disabled for accessibility and piped use (glow auto-detects; CLIs honor `NO_COLOR`).
- Evidence: `commands.py::list_concepts` has no `--format`; `Console()` constructed without `no_color` handling.
- Fix: honor `NO_COLOR`/`CLICOLOR`; add `--format text|json` to `list` (and a `--frontmatter-only` or JSON mode for `read`); tests asserting piped output stays parseable.

**9. Runnable end-to-end onboarding: sample doc + quickstart script** — Effort: M
- Gap: a new user cannot complete the quickstart today — full ingest needs Ollama or the unintegrated parsers slice; no sample input exists.
- Evidence: `examples/` has output bundles but no input documents or script; `ingest --no-llm` path depends on `okfsmith.parsers` (not on master).
- Fix: `examples/quickstart/sample.pdf` (or .md) + `examples/quickstart/run.sh` doing `init → ingest --no-llm → validate → graph --format text`; CI runs it; tutorial.md narrates it. (Pairs with gap 3's demo.)

**10. Distribution breadth + trust signals** — Effort: L
- Gap: single install story (`pip`), no `uvx`/`pipx`/brew path documented or tested, no checksums/signatures, no packaging-status visibility.
- Evidence: README shows `pip install` and one `uvx` line; helm's install matrix and navi's repology badge are the bar.
- Fix: verify and document `pipx install okfsmith` and `uvx okfsmith` paths; publish `uv.lock`; add Sigstore signing + SBOM at release; add a packaging-status badge section; defer Homebrew formula to post-1.0.

Effort legend: **S** < 1 day · **M** 1–3 days · **L** 3+ days or external dependency.

---

## 4. Loop rules (footer)

- Round 1 complete: baseline average **5.3/10** across 6 dimensions.
- The builder addresses the gaps above (highest impact first); I re-score after each
  builder iteration until all dimensions reach 10/10.
- Hard stop: **max 12 rounds**. If scores plateau (no improvement) for **2 consecutive
  rounds**, I stop the loop and name the blockers honestly instead of inflating scores.
- Honest blockers already visible: several dimensions (packaging, demo, parts of CLI UX)
  cannot exceed ~8 until Wave-2 slices integrate (parsers/extract/validate/viz/mcp_server)
  and the package is actually published — those are integration/release blockers, not
  builder-effort blockers, and will be tagged `BLOCKED-NEEDS-INTEGRATION` /
  `BLOCKED-NEEDS-RELEASE` rather than scored up.
- No commits, no pushes were made for this review. Report only.
