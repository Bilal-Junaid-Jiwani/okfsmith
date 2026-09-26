# Review R1 — Reviewer 5: Benchmark comparison vs 8 world-class dev-tool CLIs

- **Reviewer:** Reviewer 5 of 5 (senior team)
- **Date:** 2026-09-26
- **Round:** 1 (baseline)
- **Scope read-only:** `~/workspace/projects/okfsmith/` (master: scaffold, core lib, README.md, docs/OVERVIEW.md, examples/bundles/, .contract/ fixtures) + CLI implementation on `/tmp/wt-cli` branch `feat/cli` (7 commands: init, ingest, validate, list, read, graph, mcp). No commits, no pushes.
- **Status caveat:** Scored on what EXISTS. The CLI's supporting slices (`okfsmith.parsers`, `okfsmith.extract`, `okfsmith.validate`, `okfsmith.viz`, `okfsmith.mcp_server`) are lazy-loaded contracts — the commands are wired, but `ingest`, `validate`, `mcp`, and `graph --format html` currently exit 1 on this branch until those slices land. Where integration is pending, scores are marked **provisional**.

---

## 1. Benchmark tools studied (web + GitHub README)

| # | Tool (repo) | Primary takeaway |
|---|---|---|
| 1 | stripe/stripe-cli | Demo GIF directly under the hero bullets; per-OS install (npm, Homebrew, GPG-signed apt repo, yum, Scoop); `stripe login` browser pairing + `stripe login --interactive` for CI; `stripe sandbox create` for no-account trial; config at `~/.config/stripe/config.toml`; telemetry opt-out env var; full docs offloaded to docs.stripe.com. |
| 2 | vercel/vercel | Logo + "Develop. Preview. Ship." tagline above install; `npm i -g vercel`; `vercel init` example picker → `vercel` deploy in 3 lines; `login` / `whoami` / `switch` / `link` auth-context pattern; `--yes` non-interactive flags; README deliberately short, everything delegated to vercel.com/docs/cli; native binaries as opt-in. |
| 3 | supabase/cli | Centered wordmark + npm/build/Discord badges; `npm i -g supabase`; `supabase init` → `supabase start` local Docker stack → `link`; `login --no-browser` headless variant; **generated** reference docs + parity tracker kept in-repo; `supabase status`; winget/Scoop install options; README explicitly brief by policy ("command details live in generated docs"). |
| 4 | superfly/flyctl | Multi-OS install (brew, `curl fly.io/install.sh`, PowerShell, GitHub releases); `fly auth login`/`auth signup`; `fly.toml` in cwd implicitly selects the app (zero-flag context); `fly launch` wizard; **automatic background updates** (weekly sync check, severe-out-of-date re-exec, disabled in CI, Windows prompts); deploy tokens for CI. |
| 5 | netlify/cli | README with auto-generated TOC + per-command table linking to cli.netlify.com reference; install guidance includes CI discipline (pin locally, lockfile, renovate/dependabot — never `npm i -g` latest in CI); `netlify login` OAuth + `NETLIFY_AUTH_TOKEN` CI escape hatch; `netlify status` (auth + link state in one); `netlify init` interactive wizard with arrow-key prompts; `.netlify/state.json` local state with `.gitignore` guidance. |
| 6 | firebase/firebase-tools | Badges (npm, node, version) + one-click MCP install badge (Cursor deeplink); npm **and** standalone binary (`curl -sL firebase.tools \| bash`); `login` (browser), `login:ci` (CI token), `login --no-localhost` (copy-paste code for SSH), `login:add/list/use` multi-account; `init` wizard writes firebase.json; emulator suite (`demo-` projects, no login needed); `firebase mcp` ships in the same binary. |
| 7 | cloudflare/workers-sdk (wrangler) | README: npm-downloads badge, contributors, Discord, `npx wrangler init my-worker -y` quick start, system-requirements collapsible; `wrangler login` OAuth; `wrangler secret put` prompts for values (never on the command line); interactive resource-creation prompts ("Would you like Wrangler to add it on your behalf?"); real docs live on developers.cloudflare.com/workers/wrangler — README is thin by design. |
| 8 | railwayapp/cli | Install one-liner with agent setup (`--agents` flag), `railway setup agent` configures agent tools; `railway login` / `--browserless`, **auto-detects headless** and switches to device-code flow; **`railway up` as agent-friendly onboarding** (self-validates auth, unauth → sign-in, unlinked → auto-create project+service+deploy); `--json` structured errors (`{"error":"Not signed in.","code":"NOT_AUTHENTICATED"}`); `railway upgrade`; agent skills + hosted MCP. Best-in-class for agent/CI UX. |

### Cross-tool patterns worth stealing (condensed)

- **Hero pattern:** logo/tagline → 3-line quickstart → demo GIF/asciinema → install. okfsmith has the text shape but no visual.
- **Install matrix:** every tool documents ≥3 channels (package manager, script, binaries) with per-OS tabs; CI installs are pinned, never "latest". okfsmith has one channel (`pip install`) pre-release.
- **Auth ladder:** browser `login` → `whoami`/`status` introspection → env-var escape hatch → headless/device-code → CI token command. okfsmith's is mostly N/A (local-first), but the *env-var table pattern* is exactly right — it just needs the missing-machine story (Ollama not running → clear error).
- **Update UX:** flyctl auto-background-update + weekly check + CI-disable; railway `upgrade` command; netlify's "pin in CI" policy; generic "Update available: X → Y / Run: …" banner. okfsmith has none.
- **Docs posture:** two schools — README-as-landing (netlify: TOC + command table + links out) vs README-minimal + docs site (vercel, wrangler, supabase with *generated* reference). Nobody puts full command reference in the README by hand.
- **Agent readiness:** railway's `--json` + structured error codes, firebase's MCP-in-the-same-binary, stripe's telemetry opt-out. okfsmith is close here (MCP server) but `--format json` coverage is partial.
- **State/context UX:** fly.toml/netlify state.json in cwd = implicit target; `status` shows auth+link in one glance. okfsmith requires the bundle dir on every command — no implicit context, no `status`.

---

## 2. Baseline scores (round 1, provisional where noted)

| # | Dimension | Score /10 | Justification (2–3 sentences) |
|---|---|---|---|
| 1 | CLI UX | **4.5** (provisional) | Command set is well-chosen (init/ingest/validate/list/read/graph/mcp) with good help text and rich tables, and the lazy-slice loader fails with clean errors. But `ingest`, `validate`, and `mcp` exit 1 until their slices land, there is no first-run wizard or `status`/`doctor`, argument order is inconsistent with the README (`ingest ./kb <source>` in README vs `ingest <source> --bundle` in code), and there are no progress bars, no `--json` on list/read, and no update check. |
| 2 | README quality | **7.5** | Strong skeleton: 60-second quickstart, why-table, features, CLI reference table, honest comparison table, trust tiers, env-var config table, roadmap with explicit non-goals, acknowledgments. Gaps: no demo GIF/screencast, PyPI badges point at an unreleased package, the quickstart documents commands whose backing slices don't exist yet, and there's no troubleshooting, no CI/non-interactive guidance, and no link to a docs home. |
| 3 | Docs | **5.5** | docs/OVERVIEW.md is a genuinely good architecture doc (8-stage pipeline diagram + cross-cutting constraints) and examples/bundles/README.md is excellent (concept tables, trust-tier ladder, validate commands). But there is no docs site or docs index, no per-command reference beyond `--help`, no troubleshooting/FAQ, no upgrade policy, no generated reference — two docs files against competitors' documentation sites. |
| 4 | Packaging/distribution | **4.5** (provisional) | pyproject.toml is clean: entry point `okfsmith = "okfsmith.cli.app:app"`, Python ≥3.10, `mcp`/`ocr`/`test` extras, Apache-2.0 classifiers. But no PyPI release exists, no release workflow/CI in the repo (no `.github/`), README advertises `uvx okfsmith` with no uv/uvx metadata or verification, and there is no standalone binary, no version pinning guidance, and no update mechanism. |
| 5 | Code quality | **6.5** (provisional) | Core is genuinely disciplined: thin-CLI/fat-core separation documented and honored, smoke tests cover bundle round-trip/frontmatter/trust-tier/index/log, env-only secrets, conventional commits. But the CLI layer on the branch has zero tests, the inter-slice contracts are comments not tests (no contract conformance check), and there's a single test file for the whole core — well below the CI-gated bar all 8 benchmarks hold. |
| 6 | Demo/onboarding | **5.0** (provisional) | The two example bundles are a real strength: 13 concepts across trust tiers, all links resolving, validated against §11 fixtures, with an examples README that doubles as a tour. But there is no demo GIF/video, no `okfsmith demo`/sample-data one-liner, the README quickstart's first real command (`ingest`) isn't wired end-to-end, and no try-it-without-install path exists yet (uvx only works post-publish). |

**Round-1 average: 5.6 / 10.**

---

## 3. TOP 10 ACTIONABLE GAPS (ranked by impact)

### 1. README quickstart disagrees with the CLI (ingest arg order)
- **Gap:** The README's hero quickstart is the first thing a user runs, and it is wrong.
- **Evidence:** README line 21 shows `okfsmith ingest ./kb docs/quarterly-report.pdf` (two positionals); the implemented command signature is `ingest(SOURCE, --bundle)` — `commands.py` lines 119–121. Copy-paste from the README would treat `./kb` as the source file and fail or ingest the wrong thing.
- **Fix:** Pick one interface and align both. Recommendation: keep `--bundle` optional with cwd-default (see gap 2) OR change README to `okfsmith ingest --bundle ./kb docs/quarterly-report.pdf`. Add a test that runs every README code block's syntax against `typer` parsing.
- **Effort:** S

### 2. No implicit bundle context — bundle dir required on every command
- **Gap:** flyctl reads `fly.toml` in cwd; netlify uses `.netlify/state.json`; okfsmith forces the bundle path on every invocation, and there's no `status` command to show where you are.
- **Evidence:** All 7 commands take a directory argument/option; no command discovers a bundle from cwd; no `okfsmith status`. The README quickstart repeats `./kb` four times.
- **Fix:** Default the bundle argument to `.` when the cwd contains `index.md`+`log.md` (or an `.okfsmith` marker); add `okfsmith status` printing bundle path, concept count, trust-tier breakdown, and last validation result (netlify `status` pattern: auth+link in one glance). Update README examples to the shorter form.
- **Effort:** M

### 3. No demo artifact (GIF/video) and no one-command demo
- **Gap:** stripe puts a demo GIF under the hero; wrangler's README opens with a runnable hello-world; okfsmith's README is text-only and its quickstart's first real command isn't wired end-to-end.
- **Evidence:** README has zero images; `examples/bundles/` exists but nothing generates a bundle from scratch in one command; `init` scaffolds empty, `ingest` needs slices. No asciinema/vhs recording in the repo.
- **Fix:** (a) Add `okfsmith demo` (or `init --demo`) that scaffolds the cs-curriculum-style sample bundle end-to-end once slices land; (b) record a terminal GIF (vhs/asciinema) of `init → ingest --no-llm → validate → graph` and embed it under the hero. Track as launch-blocking polish.
- **Effort:** M (S for the `demo` command once slices exist; M for recording/pipeline)

### 4. JSON output coverage is partial — no agent contract
- **Gap:** railway's `--json` with structured error codes is the agent-era standard; okfsmith has `--format json` on `validate` and `graph` but `list`/`read`/`init` are text-only, and errors are free-form strings.
- **Evidence:** `commands.py`: `validate` and `graph` accept `--format`; `list_concepts`, `read`, `init` have no machine-readable mode; error messages like `"error: 'x' is not available on this branch yet."` carry no code.
- **Fix:** Add a global `--json` (or `--format json` on all commands) emitting `{"ok": bool, "code": ..., "data": ...}`; define error codes (`NOT_A_BUNDLE`, `CONCEPT_NOT_FOUND`, `SLICE_MISSING`, `VALIDATION_FAILED`). Document the agent contract in README (railway SKILL.md pattern). Tests assert JSON shape.
- **Effort:** M

### 5. No update/version UX
- **Gap:** flyctl auto-updates in background with a weekly check (disabled in CI); railway has `railway upgrade`; netlify documents CI pinning. okfsmith has `--version` and nothing else.
- **Evidence:** `app.py` implements only a `--version` callback; pyproject has no release workflow; no `.github/` directory at all.
- **Fix:** (a) Add PyPI version-check with TTL cache + opt-out env var (`OKFSMITH_NO_UPDATE_CHECK`), printing the standard "Update available: x → y / Run: pip install -U okfsmith" banner to stderr; disabled automatically when non-TTY/CI. (b) Add release workflow + document CI pinning policy (netlify's lockfile guidance) before 1.0.
- **Effort:** M

### 6. Missing first-run / missing-dependency guidance (the Ollama story)
- **Gap:** The README says "LLM features default to a local Ollama model" but nothing in the CLI checks for Ollama, explains how to install it, or degrades gracefully; benchmarks obsess over this layer (firebase `login --no-localhost`, railway auto device-code, wrangler "would you like me to add it?" prompts).
- **Evidence:** README Configuration section lists `OKFSMITH_MODEL` only; `ingest` has `--no-llm` but no `doctor`/`status` to verify prerequisites; `_lazy_attr` error text ("not available on this branch yet") is branch-scaffolding language that will confuse real users if it ever surfaces.
- **Fix:** Add `okfsmith doctor` checking: Ollama reachable, Tier-1 parsers importable, bundle dir valid — each failure printing the exact install command. Gate `ingest` on this check with a clear "run with --no-llm or install Ollama" message. Reword `_lazy_attr` errors to user-facing language ("this feature isn't installed in this build").
- **Effort:** M

### 7. No CI / release automation / docs-index hygiene
- **Gap:** All 8 benchmarks ship with CI badges that actually run (tests, release on tag); okfsmith has no `.github/`, no badge-run CI, and shields.io badges in the README pointing at a PyPI project and GitHub repo that don't exist yet.
- **Evidence:** `ls ~/workspace/projects/okfsmith/.github` → absent; README badges reference `pypi.org/project/okfsmith` and `github.com/Bilal-Junaid-Jiwani/okfsmith` pre-creation; tests run locally only (`pytest`).
- **Fix:** Add `.github/workflows/ci.yml` (pytest + contract fixtures on 3.10–3.12) and a release workflow; mark pre-release badges as such or comment them out until publish; add a `docs/` index README linking OVERVIEW.md + examples.
- **Effort:** S

### 8. No interactive onboarding wizard for `init`/`ingest`
- **Gap:** `vercel init` picks an example project; `netlify init` walks through team/site prompts; `firebase init` scaffolds firebase.json; `okfsmith init` takes a bare directory and prints two lines.
- **Evidence:** `init` command has only `--force`; no prompts for bundle name/description/default trust behavior; no `ingest` interactive mode asking which tier to use when Tier 2/3 would be needed.
- **Fix:** Make `init` interactive when no directory is given (prompt bundle name, description → write into index.md front matter), with `--yes`/`--non-interactive` escape hatch for CI (vercel `--yes` pattern). Keep `init <dir>` non-interactive as-is.
- **Effort:** S

### 9. Secrets/config posture is stated but unenforced in UX
- **Gap:** The README's "Keys are read from the environment only — never from files, flags, or the repo" is excellent policy, but nothing stops a user from passing a key via `--model` (free text) or pasting one into a prompt; benchmarks make this structural (wrangler `secret put` prompts, firebase `login:ci`).
- **Evidence:** `--model` accepts arbitrary strings; no config file story at all (`~/.config/okfsmith/config.toml` doesn't exist); no `config --list`-style introspection like stripe.
- **Fix:** Add `~/.config/okfsmith/config.toml` with `okfsmith config list/set/unset` (non-secret settings only: default model, tier preferences, telemetry), keep keys env-only, and add a pre-flight check warning if a value looks like a key (sk-/sk-ant- prefix) in any flag. Document the precedence chain (flag > env > config > default) in README.
- **Effort:** M

### 10. README lacks troubleshooting, CI/non-interactive docs, and a docs home link
- **Gap:** Every benchmark README either contains or links a troubleshooting/CI section and a docs site; okfsmith's README ends at Contributing/License with no "it broke, now what?" and no `--help`-beyond-help reference.
- **Evidence:** README has no Troubleshooting, no FAQ, no "Running in CI" subsection; docs/ has no index; `validate --strict` exists but CI exit-code semantics (exit 1 on errors) are undocumented.
- **Fix:** Add README sections: Troubleshooting (Ollama not running, bundle not found, slice-missing errors), CI usage (`--format json`, exit codes, `--strict`, non-interactive flags), and a docs/ index. After first release, adopt the supabase policy: generated command reference (`okfsmith <cmd> --help` → docs/REFERENCE.md generated, never hand-maintained).
- **Effort:** S

---

## 4. Loop-rule footer

- **Round:** 1 of max 12. **Average 5.6/10 — no dimension at 10/10; loop continues.**
- **Plateau counter:** 0 (first scoring).
- **Honest blockers (not fixable by the builder alone):** (1) PyPI/GitHub publication is an owner action — Packaging cannot exceed ~7 until the first real release exists. (2) A demo GIF and real user-tested onboarding copy need a working end-to-end pipeline (slices pending) and ideally one external user run. (3) A docs site (docs.okfsmith.dev or GitHub Pages) is an infra/owner decision — Docs will cap around ~8 without it.
- **Re-score instruction:** After builder iterations, re-run this rubric against the same materials; flag any dimension that regresses.
