# BUILD_LOG.md — okfsmith

> A running log of every major decision in this build, written for the project owner (a student) to follow along. Newest entries at the bottom.

## 2026-09-26 — Project kickoff

**What we're building:** `okfsmith`, an open-source Python CLI that converts messy documents
(PDFs, markdown, wikis, Notion exports) into Google's **Open Knowledge Format (OKF) v0.2**
knowledge bundles — markdown files + YAML frontmatter, `index.md`, `log.md` — with validation,
an MCP server, and a SKILL.md pack. The white space: nobody ingests messy documents into OKF;
existing tools all start from markdown/code.

**Spec source of truth:** `GoogleCloudPlatform/open-knowledge-format` repo, SPEC.md v0.2.
The old `knowledge-catalog/okf/` copy is a FROZEN SNAPSHOT — we do not build against it.

## 2026-09-26 — Name decision (coordinator)

"okforge" is dead: PyPI has `okforge 0.11.0` (active KB engine) and GitHub has
`jeromeetienne/okforge` (Node tool generating OKF bundles — same problem space).
PyPI `okf` and `okf-cli` are also taken. Verified 2026-09-26:

| Candidate | PyPI | GitHub |
|---|---|---|
| `okf-forge` | free (404) | collision: `glaucodeveloper/okf-forge` (Nim, 0★, abandoned — unrelated but noisy) |
| `okfsmith` | free (404) | **zero hits — clean** |
| `bundleforge` | free (404) | collision: `VerumHades/BundleForge` ("bundler and release automation" — different space) |

**Decision: `okfsmith`.** Clean on PyPI and GitHub. Repo: `Bilal-Junaid-Jiwani/okfsmith`.
Package/command: `okfsmith`. License: Apache-2.0.

## 2026-09-26 — Team & plan

20-person senior team: coordinator/principal architect (me) + 19 specialists.
Waves:
1. Foundation — spec-analyst, backend-lead (scaffold + core bundle I/O), tech-writer (README draft), data-engineer (2 sample bundles).
2. Slices (each on own git worktree/branch) — CLI, parsing tiers, §11 validator, 2-pass LLM extraction, FastMCP server, SKILL.md pack, viz.html.
3. Hardening — tests, CI/DevOps, security review, performance review, DX/launch assets.
4. Review gate (staff reviewer) → integration → release (CHANGELOG, GitHub repo, push).

Rules: small vertical slices, tests with every slice, nothing merges without review,
conventional commits, no secrets in repo (LLM defaults to local Ollama; API keys via env vars only),
no vector DB, no attestation execution runtime.

## 2026-09-26 — Key architecture decisions (from research brief)

- **Parsing tiers (free-first):** Tier 1 = LiteParse (PDFs, Apache-2.0) + MarkItDown (everything else, MIT),
  both local, no keys. Tier 2 = Docling sidecar (optional). Tier 3 = cloud OCR (LlamaParse/Mistral/Azure DI)
  only for scanned pages — born-digital stays on Tier 1. (Avoid PyMuPDF: AGPL.)
- **Extraction:** 2-pass LLM. Pass 1 cheap model drafts concept JSON with Anthropic-style contextual
  situating prefix (doc title + section path + doc summary) stamped into each concept. Pass 2 critic
  verifies (contradictions, claim fidelity, stub detection). Claims → `[^source-id]` footnotes →
  `sources[]` entries. `generated: {by: <tool>/<model>, at}` stamped; `verified` only after review.
  Trust tiers derive: unverified → machine-confirmed → human-reviewed.
- **Dedup:** SHA-256 source dedup + normalized-title/resource match + ~~embedding similarity~~ [superseded: embedding similarity is a v1 TODO, not implemented — see 2026-09-26 correction], LLM adjudicates merges.
- **Conformance:** implement OKF §11 natively (3 hard rules) + advisory lints (orphans, dead links, stubs,
  missing recommended fields, legacy v0.1 fields). Broken links = warnings, never errors (spec §6).
- **MCP:** FastMCP, stdio default, tools `search/get/list/neighbors/index`; `okfsmith mcp --bundle ./kb`.
- **Layout:** `src/` layout, `core/` = business logic, `cli/` = Typer layer, extras `mcp`, `ocr`.

## 2026-09-26 — Wave 1 dispatched (foundation)

- spec-analyst → `.contract/spec_decisions.md` + conformance fixtures (live SPEC.md v0.2).
- backend-lead → repo scaffold: `src/okfsmith/` (core bundle I/O, spec constants), Typer app stub, pyproject, LICENSE, git init.
- tech-writer → README.md (landing-page style) + docs/OVERVIEW.md.
- data-engineer → `examples/bundles/cs-curriculum/` + `examples/bundles/okf-primer/`.
Each owns disjoint paths; integration after wave 1 lands.

## 2026-09-26 — Wave 2 dispatched (vertical slices, isolated worktrees)

Each slice engineer works in /tmp/wt-<slice> on branch feat/<slice>, conventional commits, tests required.
- cli: 7 Typer commands (init/ingest/validate/list/read/graph/mcp), thin cli/ over sibling modules (lazy imports).
- parsing: parsers/ — LiteParse or pypdf (no PyMuPDF), MarkItDown for office formats, Notion zip handler, scan router, deterministic sectioning, ingest_no_llm, SHA-256 manifest.
- validate: validate/check() implementing E001–E004/W001–W015 verbatim from .contract; fixture-driven tests vs EXPECTED.json.
- extract: 2-pass LLM (Ollama default OpenAI-compatible, env keys only), contextual situating prefix, claim→sources[] footnotes, critic pass, dedup, human_review stamping.
- mcp: FastMCP server, tools search/get/list/neighbors/index, stdio, read-only.
- skill: skills/okfsmith-build/ per agentskills.io + standalone validate.py script + 3 references.
- viz: viz/render_html(bundle_root, output) → self-contained offline viz.html (dependency-free JS).
Contracts exchanged: cli ← ingest_no_llm(bundle, parsed, source_id), extract.run(bundle, sections, ...), validate.check(path), viz.render_html(root, output), mcp_server.serve(path, transport).

## 2026-09-26 — TEAM EXPANSION: 20 → 54 members (user correction)

- User clarified: the 34 extra senior members announced earlier belong to the OKF open-source project (okfsmith), NOT Technovora. Technovora stays on its original 6-member loop (handled separately).
- okfsmith team expands from 20 to 54. Existing 20 roles unchanged (coordinator/principal architect + 19 specialists across waves 1–3).
- New 34, website roles adapted to an open-source Python CLI:
  - 5 REVIEWERS: benchmark okfsmith vs top 40 international open-source dev tools/CLIs (CLI UX, README, docs, packaging, code quality, demo). Per-dimension scores → builder. Loop: builder improves → re-score → repeat until 10/10 all dimensions. Safety: max 12 rounds; stop if plateau 2 consecutive rounds, report blockers honestly.
  - 15 UI/UX DESIGNERS (5 panels × 3): CLI UX/DX, README-as-landing-page, docs, viz.html, demo experience. Supervise + approve builder output every iteration; best-in-class or nothing.
  - 5 QA TESTERS: full QA pass after integration — pytest, integration tests, Linux/macOS/Windows, pip/uvx installs, edge cases, no broken commands.
  - 5 SEO / AI-SEO SPECIALISTS: research how AI SEO is done in 2026, keyword research, implement discoverability (GitHub repo SEO, PyPI listing, docs SEO, awesome-list placements). Honest: no one can guarantee #1; do everything legitimate, report realistic expectations.
  - 4 SECURITY / CYBER EXPERTS: audit package — dependencies, supply chain, secrets hygiene, leaked credentials. Fix everything found; re-verify at release.
- Sequencing: reviewers/UX/seo/security start now on current tree; QA starts after Wave-2 integration. Reviewer round-1 = tool research + rubric + baseline scores now, full product re-score after integration, then builder loop.

## 2026-09-26 — Expansion wave dispatched (19 specialists now active)

- 5 REVIEWERS (r1-reviewer-1..5): each benchmarks 8 of 40 tools (1: gh/git/docker/kubectl/terraform/ansible/aws-cli/azure-cli; 2: uv/ruff/pipx/httpie/rich-cli/cookiecutter/black/mkdocs; 3: bat/fd/ripgrep/eza/fzf/starship/zoxide/delta; 4: lazygit/gitui/k9s/helm/gum/glow/just/navi; 5: stripe-cli/vercel/supabase/flyctl/netlify/firebase-tools/wrangler/railway). Reports → .contract/reviews/r1-reviewer-N.md. Loop until 10/10, max 12 rounds, plateau-stop after 2.
- 15 UI/UX DESIGNERS as 5 panels × 3: A=CLI UX, B=README landing page, C=docs/onboarding, D=viz.html, E=packaging/demo DX. Verdicts → .contract/ux/panel-*.md; re-review every builder iteration.
- 4 SECURITY: 1=supply chain, 2=secrets hygiene, 3=code review, 4=release/packaging. Audits → .contract/security/audit-N.md; re-verify at release.
- 5 SEO: 1=AI SEO 2026 market research, 2=keywords, 3=GitHub repo SEO assets, 4=PyPI metadata diff, 5=docs SEO + awesome lists. Plans → .contract/seo/. Honest: no #1 guarantees.
- 5 QA TESTERS: queued — start after Wave-2 integration (validate/extract/parsing still running).
- Roster now 54: 1 coordinator + 53 specialists (19 original + 34 new).

## 2026-09-26 — Reviewer round-1 complete (all 5 reviewers, 40 tools)

Baseline scores vs top-40 international CLI/dev tools (6 dimensions, 0–10):

| Reviewer | Tools | CLI UX | README | Docs | Packaging | Code | Demo | Mean |
|---|---|---|---|---|---|---|---|---|
| R1 | gh/git/docker/kubectl/terraform/ansible/aws/azure | 6.0 | 7.5 | 5.5 | 5.0 | 6.5 | 6.0 | 6.08 |
| R2 | uv/ruff/pipx/httpie/rich-cli/cookiecutter/black/mkdocs | 7.5 | 8.0 | 6.5 | 5.5 | 8.0 | 6.0 | 6.92 |
| R3 | bat/fd/ripgrep/eza/fzf/starship/zoxide/delta | 5.5 | 7.5 | 6.0 | 3.5 | 6.5 | 4.5 | 5.58 |
| R4 | lazygit/gitui/k9s/helm/gum/glow/just/navi | 6.0 | 7.0 | 4.5 | 3.5 | 7.0 | 4.0 | 5.33 |
| R5 | stripe-cli/vercel/supabase/flyctl/netlify/firebase/wrangler/railway | 4.5 | 7.5 | 5.5 | 4.5 | 6.5 | 5.0 | 5.58 |
| AVG | | 5.9 | 7.5 | 5.6 | 4.3 | 7.1 | 5.3 | 5.90 |

Top recurring gaps for builder round 1: (1) README quickstart ingest signature wrong (all 5); (2) unpublished PyPI/GitHub → install fiction; (3) no shell completions (add_completion=False); (4) no man page; (5) no --dry-run for ingest; (6) no --format json machine contract; (7) no demo artifact; (8) no lint/format config or CI; (9) SKILL.md/MCP advertised as shipped but unmerged; (10) example bundles W011 bare-date stale_after + frozen-snapshot citations.
Honest 10/10 blockers: slice integration, PyPI/GitHub publication, real LLM extraction quality, real users. Loop armed: builder round 1 → re-score → max 12 rounds, plateau-2 stop.
UX panels B/C/E verdicts: CHANGES-REQUIRED (blockers logged). Panels A/D pending. Security audits + SEO-5 pending. QA queued post-integration.

## 2026-09-26 — SEO 5/5 complete; security re-dispatch

- All 5 SEO plans delivered: ai-seo-research-2026.md, keyword-research.md, github-seo.md, pypi-seo.md, docs-awesome.md (14-page docs plan, llms.txt draft, 11 verified awesome-list targets with week-by-week outreach order).
- UX panels: A/B/C/E verdicts in (all CHANGES-REQUIRED); D (viz) pending.
- One security expert errored on inference timeout with no output; re-dispatched as code-security-review scope. Will verify all 4 audit scopes are covered once the 3 running audits land and fill any gap.
- Duplicate SEO-5 re-spawn closed (original delivered after all).
- Still running: parsing slice, UX-D, 3 security audits + 1 re-dispatched.

## 2026-09-26 — Wave 2 complete; integration started

- Parsing slice landed: liteparse VERIFIED on PyPI (2.14.7, Apache-2.0, fully offline) as Tier-1 PDF parser; PyMuPDF avoided (AGPL). markitdown[docx,pptx,xlsx] for office formats. 34/34 tests green.
- All 7 slices committed on feat/* branches. Integration architect dispatched: merge all into `integrate/wave2`, wire CLI lazy contracts to real signatures (ingest_no_llm(bundle, parsed, source_id), extract.run(bundle, sections, ...), validate.check→Finding.as_dict()), full pytest green, CLI end-to-end smoke test. Staff review gate owns the merge to master.
- Known contract mismatches to adjudicate at integration: CLI assumed ingest_no_llm(sources, bundle) and extract.run(sources, bundle, model); real signatures differ (documented above).

## 2026-09-26 — Integration green; staff review gate

- integrate/wave2 merged all 7 slices (d60e76a). Conflicts: pyproject union, conftest dedupe. CLI contracts wired to real signatures. Full suite: 160 passed, 19 skipped, 0 failed. CLI smoke (init/ingest--no-llm/validate/list/graph--html) all exit 0. One integration bug fixed: is_ollama_reachable() now never raises (proxy-env ValueError was masking LLMUnavailableError).
## 2026-09-26 — v0.1.0 RELEASED (merge → GitHub → package build)

- **Release hygiene (audit-4 HIGH, minimal):** `license = "Apache-2.0"` PEP 639 SPDX
  expression (+`license-files`, setuptools>=77, dropped superseded OSI classifier
  which new setuptools rejects alongside license expressions); new `MANIFEST.in`
  with explicit sdist policy: `prune .contract`, `exclude BUILD_LOG.md`.
  No feature work, no round-1 items.
- **Merge:** `integrate/wave2` → `master` as `8515b62` (staff review-gate APPROVED).
- **GitHub:** public repo created `Bilal-Junaid-Jiwani/okfsmith`
  (https://github.com/Bilal-Junaid-Jiwani/okfsmith) — "Convert messy documents
  into Google OKF v0.2 knowledge bundles for AI agents", Apache-2.0.
  `master` pushed as default branch. Note: plain `git push` over HTTPS cannot
  authenticate from this environment (surrogate is api.github.com-only), so the
  18-commit history was replicated byte-identically via the Git Data API
  (verified: remote master tree SHA == local master tree SHA).
- **Package build:** `python -m build` → `okfsmith-0.1.0.tar.gz` +
  `okfsmith-0.1.0-py3-none-any.whl`; verified `.contract/` and `BUILD_LOG.md`
  are NOT in the sdist/wheel; `LICENSE` IS included (PEP 639 license-files);
  `twine check` PASSED on both artifacts.
- **PyPI upload: BLOCKED** — no API token available yet. Everything except the
  upload is done; `dist/` artifacts are ready for `twine upload` once a token
  is provided.
- Known remaining item (pre-existing, not release-blocking): markitdown
  `>=0.1` floor admits vulnerable versions (CVE-2025-11849, CVE-2025-64512) —
  fix (raise floor, move to `office` extra) queued for builder round 1.

## 2026-09-26 — PyPI upload attempted; token rejected (403)

- Wrote `~/workspace/skills/pypi/bin/upload.py` (compiled): multipart POST to
  `https://upload.pypi.org/legacy/` with `Authorization: Bearer <surrogate>`
  (verified against pypi/warehouse source that Bearer macaroons are accepted;
  Basic auth deliberately avoided since base64 would hide the surrogate from
  Sentinel). Sdist uploaded first, then wheel.
- **Result: HTTP 403 "Invalid or non-existent authentication information" on
  both files. Nothing was published** (first upload creates the project; 403
  means no project/files were created — safe to retry).
- Mechanism proven NOT at fault: (1) uploader verifies the outgoing request
  carries the surrogate before sending; (2) same Bearer-surrogate pattern
  against api.github.com returned HTTP 200; (3) egress goes via the proxy
  (no_proxy does not bypass upload.pypi.org). The stored `custom.pypi` token
  itself is therefore invalid/wrong.
- Likely causes: token pasted incorrectly, token created on test.pypi.org
  instead of pypi.org, wrong scope, expired/deleted, or a password pasted
  instead of an API token.
- Next step: replace the token via `credentials.request_api_access`
  (provider `pypi`, `reconnect: true`), then re-run the uploader. User must
  create the token at **pypi.org** (not test.pypi.org) → Account settings →
  API tokens → Add API token, scope **Entire account**, paste the `pypi-…`
  value into the secure card.

## 2026-09-26 — PyPI release: okfsmith 0.1.0 LIVE

- Root cause of the earlier 403s found and fixed: the `custom.pypi` connector
  had been registered with `custom_header:Authorization` placement while the
  uploader sent `Authorization: Bearer <surrogate>` (the Warehouse-accepted
  form, verified from pypi/warehouse source). Re-registered with
  `bearer_header` placement and switched `~/workspace/skills/pypi/bin/upload.py`
  to the blessed `add_surrogate_to_request()` helper — fully consistent with
  the GitHub-proven pattern.
- Also fixed: uploader now sends `metadata_version` (read from each artifact's
  own PKG-INFO/METADATA); Warehouse returned 400 without it after auth passed.
- Upload result: `okfsmith-0.1.0.tar.gz` → HTTP 200, `okfsmith-0.1.0-py3-none-any.whl`
  → HTTP 200 (both via https://upload.pypi.org/legacy/).
- Verified live: https://pypi.org/project/okfsmith/ (HTTP 200),
  https://pypi.org/pypi/okfsmith/json shows version 0.1.0 with 2 files.
- Install: `pip install okfsmith`
- Remaining known item (not release-blocking): markitdown `>=0.1` floor admits
  CVE-2025-11849 / CVE-2025-64512 — queued for builder round 1.

## 2026-09-26 — Polish round 1 (CLI rewrite + Panel-D viz + docs + packaging)

**CLI rewrite (uncommitted until now):** bundle is now the first positional
argument everywhere (`okfsmith ingest BUNDLE SOURCE...`); `--format`/`--tier`/`--transport`
are constrained enums (exit 2 on misuse); path/flag validation happens before
lazy imports; stable `error [CODE]:` messages with hints and no tracebacks;
JSON error objects for JSON commands; `init --force` confirms (bypass with `--yes`);
`--model` + `--no-llm` is a usage error; `ingest` gained multi-source,
`--recursive`, `--dry-run`, `--quiet`, TTY progress; `validate --format json`
reports `status`/`concepts`/`error_count`/`warning_count`; `list`/`read` gained
JSON modes; new `doctor` command; datetime frontmatter coerced to ISO strings
in JSON output; trust-tier validation; all dynamic Rich table content escaped;
`okfsmith --version`, bare `okfsmith` exits 0 with first-run help.

**Viz Panel-D:** fixed `#empty[hidden]` overlay swallowing pointer events;
honest two-channel legend (trust=shape, type=color); Okabe–Ito colorblind-safe
palette; focusable canvas + keyboard controls (arrows pan, +/- zoom, 0 reset,
Esc close); screen-reader concept list; reset-view button; match count;
one-hop neighborhood emphasis; detail panel with backlinks + dead-link
connections + reduced metadata; minimal markdown rendering (code/strong/em/link
only); empty/loading/error overlays; chunked layout for large graphs; fixed
Python SyntaxWarning from template escapes (JS output byte-identical,
node --check OK).

**Packaging/docs:** `pyproject.toml` metadata (description, keywords,
classifiers, URLs); Ruff config (`[tool.ruff]`, target py310); full docs set
(index/install/quickstart/commands/pipeline/parsing/llm/validation/mcp/skill/
troubleshooting/faq) + README rewritten to match the real CLI grammar;
`llms.txt`, `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`.

**Verification:** 181 passed, 20 skipped (full suite); CLI smoke green
(init/ingest/validate/list/read/graph-mermaid/mcp-transport-rejection);
`python -m build` + `twine check` PASSED; artifact scan clean
(no secrets, no `extractall`, no PyMuPDF); ruff clean on all touched files
(83 pre-existing errors elsewhere in tree left untouched); rendered-JS
`node --check` OK.

## 2026-09-26 — Polish round 1, follow-up fixes

**Security fix (reviewer-found, release-blocking):** the viz `md()` JS renderer
turned markdown links into `<a href>` without scheme restriction — a
`javascript:` URL in an ingested document's description/body became a clickable
XSS payload. Fixed with a `safeHref()` gate: only `http:`/`https:`/`mailto:`,
fragments, and relative URLs become anchors; anything else (including
`data:`, `vbscript:`, protocol-relative) degrades to plain text. Verified with
node: `javascript:`/`data:` render as text, https/mailto/fragment/relative
still link, `node --check` clean. Regression test added
(`test_viz_markdown_links_restrict_url_schemes`).

**Parser regression fix (clean-install smoke found it):** moving MarkItDown to
the `office` extra had routed `.md`/`.txt` through `office.parse_office`, so a
base install could not ingest markdown at all. New `parsers/text.py` reads
`.md`/`.markdown`/`.txt` with the stdlib (UTF-8, `errors="replace"`, pipe
tables extracted); `parse_file` routes there before the office fallback.
Proven with markitdown import-blocked
(`test_txt_and_md_parse_without_office_extra`); clean-venv sdist install now
ingests `.md` → 2 concepts, conformant.

**Also:** `python -m okfsmith.cli` entry point (no more runpy warning);
`add_completion=True` + static `completions/` scripts (bash/zsh/fish, dynamic
shims verified: commands and enum values complete); `man/okfsmith.1`;
`.github/workflows/ci.yml` (test matrix 3 OS × 4 Python, ruff, CLI smoke,
build+twine, pip-audit + secret/forbidden-content scan); `MANIFEST.in`
extended to ship docs/completions/man in the sdist; install.md completion
docs corrected for Click 8.5.

**Verification:** 183 passed, 20 skipped; ruff clean on touched files;
`python -m build` + `twine check` PASSED; sdist contains completions/man/docs;
clean-venv install smoke green (init/ingest/validate/graph-html).

## 2026-09-26 — Polish round 2 (UX/consistency audit)

**CLI consistency:** the bundle positional is now named `bundle` in every
command, so usage lines read `{bundle}` everywhere (was a mix of `{bundle}`
and `{directory}`); `--tier` error no longer stutters ("Invalid value:
--tier 'bogus' is not one of: ..."); `init` help says BUNDLE.

**Ingest hygiene:** directory scans now skip the reserved `index.md`/`log.md`
(an ingested bundle no longer tries to turn its own manifest into concepts);
explicitly named files are still honored. Test added.

**Bug fixed (found by UX walk-through):** `read` of a missing concept printed
the `Bundle` object's repr in the error message and hint (regression from the
arg rename). Now shows the bundle path; regression test asserts no
"Bundle object at" leaks.

**Verification:** 185 passed, 20 skipped (full suite); CLI tests 57 passed.

## 2026-09-26 — Polish round 2 continued (repr-leak sweep, hints, typo)

**Bundle repr leaks eliminated:** `init`'s success message, `list`'s table
title, and `read`'s missing-concept error all interpolated the `Bundle`
object's repr (`<okfsmith.core.bundle.Bundle object at 0x...>`) instead of
the bundle path. Each now captures `bundle_path` before `Bundle.load()` and
uses it in user-facing messages. Sweep regression test
(`test_no_bundle_repr_leaks_in_user_output`) asserts no "Bundle object at"
in init/list/read output.

**Missing-extra guidance:** the `slice-not-installed` error hint and
`doctor`'s MISSING rows now cover pip, pipx, and uvx
(`_install_extra_hint`), not pip only.

**Typo:** `ingest --help` said "directorie(s)" — fixed.

**Security re-verification (safeHref):** a round-2 security review claimed a
residual XSS bypass via HTML-entity URLs (e.g. `[x](java&#115;cript:...)`
producing `<a href="java&amp;#115;...">`). Independently verified with node
(14 probes) + Python html.parser + urlsplit: esc() runs before link
extraction so every `&` becomes `&amp;`; browsers decode entities in href
attributes in a SINGLE pass, yielding literal `&#115;` text; the resulting
URL has an EMPTY scheme (urlsplit confirms) and parses as an inert relative
URL — no script execution possible. `javascript:`/`data:`/`vbscript:`/
`//evil` remain blocked; `http(s)`/`mailto`/`#frag`/relative pass. All other
innerHTML insertion sites use esc(); dynamic text uses textContent. The gate
is sound; no change made (a naive `&`-rejection would break legitimate
`?a=1&b=2` query-string URLs).

**Verification:** 186 passed, 20 skipped (full suite); ruff clean on touched
files.

## 2026-09-26 — Polish round 2 gate (all green)

- `git diff --check`: clean; `compileall`: clean; ruff clean on touched files.
- Full suite: **186 passed, 20 skipped**, 1 benign warning.
- `python -m build`: ok; `twine check dist/*`: PASSED (wheel + sdist).
- Sdist contains docs/validation.md, docs/OVERVIEW.md,
  skills/okfsmith-build/references/parsing-tiers.md.
- Wheel artifact scan: no secrets, no `extractall`; `api_key=` hits are
  env-var pass-through to the OpenAI client (no hardcoded secret);
  `pymupdf` hit is the deliberate "NOT used (AGPL)" comment.
- Clean-venv sdist install: `okfsmith --version` → 0.1.0; base install
  ingested a 2-section `.md` → 2 concepts, `validate` conformant.

Round-2 reviewer scores (evidence-backed): QA 8/10 (was 8), SEO/AI-SEO
6.5/10 (was 6.0 — skill-pack grammar fixes landed), Security 7/10 (was 8;
reviewer claimed a residual XSS bypass via entity URLs — independently
re-verified as non-exploitable, see above; gate stands).

## 2026-09-26 — Correction: real C0-control XSS bypass found and fixed

The round-2 security report contained a SECOND, separate claim beyond the
entity-URL theory: leading C0 control characters (`\x01`–`\x08`, `\x0e`–`\x1f`,
which are not matched by `\s`) bypass the `safeHref` scheme gate. This one
is REAL and was verified against the pre-fix tree (HEAD 331106b):

- `[x](\x01javascript:alert(1))` rendered as
  `<a href="\x01javascript:alert(1">` — a clickable anchor.
- The `md()` URL regex `[^)\s]+` permits C0 bytes; `safeHref` only rejected
  URLs whose FIRST character was a letter or `/`.
- Browsers strip leading C0 controls per WHATWG URL parsing, so the link
  executes `javascript:alert(1)` on click.

The earlier BUILD_LOG wording ("gate stands") covered only the entity
theory and was incomplete. Fixed in `9deff35`:

- `safeHref` now strips `^[\u0000-\u0020\u007F]+` first, mirroring browser
  behavior, before the scheme checks.
- New behavioral regression test executes the shipped `md()` in node:
  `\x01`/`\x0e`/`\x07`-prefixed `javascript:`, direct `javascript:`,
  `data:`, `vbscript:`, `//evil` produce no anchor; `https:`, `http:` with
  query strings, `mailto:`, `#frag`, relative paths keep theirs.

## 2026-09-26 — Polish round 3 fixes (post-reviewer)

Round-3 reviewer scores (HEAD 331106b, evidence-backed): QA 9.0/10, SEO/AI-SEO
8.5/10, Code 8/10, UX 8.2/10, Security 8/10 (round-2 entity claim withdrawn;
C0 claim confirmed real — fixed as above).

Additional fixes landed after the round-3 reviews:

- **CLI honesty (UX P1):** sub-1000-char sources no longer report hollow
  `ok` with 0 concepts — they report
  `skipped (below 1000-char minimum; stub prevention)` and their digest is
  NOT recorded, so retries repeat the reason instead of falsely claiming
  `already ingested`. Zero-concept ingests for other reasons report
  `skipped (no concepts created)`. `--dry-run` applies the same threshold
  (parity). Regression tests added.
- **Ruff gate green:** fixed all 61 pre-existing `ruff check src/ tests/`
  errors (TYPE_CHECKING imports, unused loop vars, `zip(strict=)`,
  dict/list idioms). CI lint step now passes.
- **Docs:** trust derived from `verified` (not a literal `trust:` field);
  critic → `machine-confirmed` documented; README badge + Changelog URL
  target `master`; embedding similarity labeled v1 TODO; parser routing
  precise; Notion CSV = one document each; `mcp --help` uvx `--with`
  example.
- **CLI:** `okfsmith mcp` without the `mcp` extra → `error [missing-extra]`
  + install hint, never a traceback.

**Gate (current HEAD 5060148):** diff-check clean; compileall clean; ruff
clean; **191 passed, 20 skipped**; `python -m build` ok; `twine check`
PASSED (wheel + sdist); clean-venv sdist install: 2940-char `.md` →
5 concepts, `validate` conformant, `graph --format json` ok.

## 2026-09-26 — Polish rounds 4 → release 0.2.0

**Round-4 reviewer scores** (branch `polish/round-1`, target HEAD `9d29e05`;
read-only, nothing changed by reviewers):
- Code: completed — 191 passed/20 skipped, all changes accounted (score line not visible in delivery preview)
- UX: 8.5/10 — all 4 round-4 UX fixes verified hands-on
- QA: 10/10 — 191 passed, 20 skipped, 0 failed; 5 new round-4 tests all pass
- SEO/AI-SEO: 9/10 — trust fiction gone, blob/main fixed, llms.txt verified
- Security: completed — all checks passed (score line not visible in delivery preview)

**Post-round-4 fixes** (HEAD 9d29e05 → release):
- `921bc8f`: examples cite canonical spec URL (not frozen snapshot);
  `list` ID column `no_wrap+fold` (copy-paste safe); BUILD_LOG supersede note
- `a1678bf`: CI `master` trigger, cross-platform smoke paths, honest PyMuPDF check
- `46744e9`: empty-list hint, graph JSON `dead_links`, invalid-output hint
- `6fe0360`: init on file path, set JSON serialization, graph `--output` all formats

**Release 0.2.0** — version bumped (`pyproject.toml`, `__init__.py`,
`GENERATED_BY`, test), CHANGELOG dated with Added/Changed/Security/Fixed.
Final gate: diff-check clean, compileall clean, ruff clean,
**191 passed, 20 skipped**; `python -m build` → okfsmith-0.2.0 wheel+sdist;
`twine check` PASSED both; isolated-venv wheel install: `--version` = 0.2.0,
init → ingest (4 concepts) → validate conformant → graph JSON with dead_links.

## 2026-09-26 — Interactive chat REPL (`okfsmith chat`)

- New `okfsmith chat [BUNDLE]` command (own "Interactive" help panel):
  Claude Code / Gemini CLI style REPL over a bundle. Plain text = question;
  retrieval via shared `rank_concepts()` (extracted from
  `BundleTools.search` so MCP search and chat rank identically); LLM backend
  (Ollama default, `OPENAI_API_KEY` fallback) synthesizes grounded answers
  with `[concept-id]` citations + Sources footer; extractive mode when no LLM
  is reachable (`--no-llm` forces it). Multi-turn follow-ups resolve against
  recent context. Hallucinated citations are stripped — every cited concept
  is a real bundle concept.
- Slash commands: `/help /ingest /list /read /search /validate /graph
  /doctor /model /clear /exit` (`/quit` alias). `/ingest` reuses the real
  ingest command and reloads the bundle. Unknown slash → hint, never crash.
- REPL details: rich banner (version, bundle, concept count, backend status),
  bundle-aware prompt (`kb › `), stdlib readline with tab-completion and
  persistent history at `~/.okfsmith/history` (env-overridable), Ctrl-C
  cancels input, Ctrl-D/EOF exits 0 with goodbye. Piped stdin works
  (`printf '/list\n/exit\n' | okfsmith chat ./kb`).
- Commits on `feature/interactive-chat`, merged to master (fast-forward):
  `42a3d0b` (rank_concepts refactor), `c1de381` (chat feature + 31 tests +
  README/CHANGELOG/docs/commands.md/man page). Gate: ruff clean,
  **222 passed, 20 skipped** (191 pre-existing + 31 new).
- GitHub: plain HTTPS push 401s from this env (as before); the 2 commits
  were replicated via the Git Data API on top of remote master `b772838`
  (tree byte-identical to local v0.2.0 base). Remote master is now
  `084ca67`; remote tree verified byte-identical to local `c1de381`.
- No version bump, no PyPI publish (release is a separate decision).

## 2026-09-26 — "Any model, any API key" (15 provider presets + --api-base)

- User asked (Roman Urdu) for API-key support for any model: Groq, Mistral,
  DeepSeek, OpenRouter, Together, xAI, Gemini, OpenAI, Ollama "or any
  custom OpenAI-compatible endpoint". Follow-ups added: 5 more presets
  (perplexity, fireworks, deepinfra, anyscale, lmstudio) and `agentrouter`
  (`https://agentrouter.org/v1`, `AGENTROUTER_API_KEY` env).
- `PROVIDER_PRESETS` (15): openrouter, groq, mistral, deepseek, together,
  fireworks, deepinfra, anyscale, perplexity, xai, gemini, openai,
  agentrouter, lmstudio, ollama. Presets store the canonical full base URL
  (backend appends only `/chat/completions`); odd shapes handled exactly —
  Perplexity has no `/v1`, Fireworks nests under `/inference/v1`, DeepInfra
  under `/v1/openai`, Gemini under `/v1beta/openai`. Custom bases via
  `--api-base`/`OKFSMITH_API_BASE` are normalized (`_normalize_custom_base`:
  bare hosts gain `/v1`, full bases never doubled).
- Flags on `ingest` and `chat`: `--provider`, `--api-base`, `--api-key`;
  all rejected with `--no-llm` (exit 2). Precedence: flags → `OKFSMITH_*` →
  legacy `OPENAI_API_KEY`/`OPENAI_BASE_URL` (+ `OKFSMITH_BASE_URL` alias) →
  preset → Ollama default. `AGENTROUTER_API_KEY` honored only when the
  provider is agentrouter (provider-scoped, never leaks into others).
  `--api-key` prints a one-time shell-history warning. Unknown provider →
  loud `LLMError` listing valid names (never silent extractive fallback).
- OpenRouter is the flagship: one key → hundreds of models via
  `vendor/model` IDs (README/docs examples use
  `--provider openrouter --model anthropic/claude-sonnet-4`).
- `--api-base` documented as covering literally anything else (Azure
  OpenAI, self-hosted vLLM, llama.cpp server, any compat proxy); Anthropic's
  native API noted as not OpenAI-compatible (needs compat proxy or the
  openrouter preset).
- Secrets: keys never logged/displayed/persisted — `redact_key`/`key_status`,
  banner/`/model`/`doctor` show only `set (hidden)`/`not set`; HTTP error
  bodies still include endpoint text (no key is ever in the URL).
- `okfsmith doctor` now reports resolved provider, base URL, model, key
  status (with source) without network probing; unknown provider → clean
  FAIL row.
- Gate: ruff clean, **268 passed, 20 skipped** (222 pre-existing + 46 new in
  `tests/test_llm_any_model.py`, mocked httpx, dummy `test-key-123` only).
- Docs: README "Use any model (API key)" section, docs/llm.md backends
  rewrite, docs/commands.md synopses, man page, CHANGELOG [Unreleased].
- Commits on `feature/any-model-api-key`, merged to master (fast-forward):
  `b91bd07` (whole feature, incl. agentrouter follow-up). No version bump,
  no PyPI publish.
- GitHub: remote master had moved to `12106f03` (user pushed `ef7104e` from
  their machine; tree == local `ef7104e`). Plain HTTPS push 401s from this
  env, so the commit was replicated via the Git Data API on top of
  `12106f03` (blobs verified against local SHAs, rebuilt trees verified
  byte-identical to local tree `18f2005d`). Remote master is now
  `613d48b0`; remote tree verified byte-identical to local `b91bd07`.

## 2026-09-26 — Chat startup UI redesign (Qwen/Claude/Antigravity aesthetic)

- User asked for the `okfsmith chat` interface to look like Claude Code /
  Antigravity CLI / Qwen CLI (sent reference screenshots). Studied the real
  screenshots via web image search first, then redesigned on
  `feature/chat-ui-redesign`, merged to master.
- New startup UI (`src/okfsmith/cli/chat.py`):
  - Giant 5-row block-letter ASCII `OKFSMITH` logo, rendered with a
    horizontal yellow→orange→magenta gradient (Qwen-style) via rich
    truecolor/256-color; per-column colors computed in `_gradient_color`.
  - Below the logo (dimmed): `okfsmith chat vX.Y.Z`, then an
    Antigravity-style info line `Bundle: <name> (<N> concepts) · <provider>
    · <model>` (or `· extractive mode`); extractive-mode notice compacted
    to one dimmed line.
  - Qwen-style "Tips for getting started:" numbered list (ask questions,
    /help, /ingest).
  - Prompt keeps bundle-awareness but styled: cyan bundle name + orange `›`
    on a tty, plain `kb › ` when piped.
  - Answers prefixed with a subtle dim-orange `✦` (extractive table title
    and a marker line before LLM Markdown).
- Plain-ASCII guarantee: `_color_enabled()` (tty + no NO_COLOR) gates all
  color; `print_styled()` falls back to markup-stripped text with
  `highlight=False` (rich auto-highlights numbers like `0.2.0` even in
  plain strings — caught by test). Piped output verified: zero ANSI codes.
- Key status removed from the banner (still masked in `/model` and
  `doctor`); `test_banner_masks_key` updated accordingly.
- Gate: ruff clean, **277 passed, 20 skipped** (268 pre-existing + 9 new
  banner/prompt/marker tests in `tests/test_chat.py`).
- Docs: README "Interactive chat" transcript replaced with the new look,
  CHANGELOG [Unreleased] → Changed.
- Commits on `feature/chat-ui-redesign`, merged to master. No version bump,
  no PyPI publish.
- GitHub: plain HTTPS push 401s from this env, so commit `fccea8d` was
  replicated via the Git Data API on top of remote master `eb163b72`
  (remote tree == local parent tree, fast-forward safe). All 6 blobs
  verified against local SHAs; rebuilt tree verified byte-identical to
  local tree `af9c084f`. Remote master is now `1b19f58e`; remote tree
  verified byte-identical to local.

## GitHub Pages — docs site

The docs site in `docs/` is built to deploy as a standalone GitHub Pages
source. Enabling it requires the repo owner to do this in the GitHub UI —
it cannot be done from here:

1. GitHub → repo **Settings** → **Pages**.
2. Under "Build and deployment", source: **"Deploy from a branch"**.
3. Branch: **`master`**, folder: **`/docs`** → **Save**.

Notes:

- Public URL once enabled: `https://bilal-junaid-jiwani.github.io/okfsmith/docs/`
  (matches the SEO canonical base used in `docs/` `<link rel="canonical">`,
  `og:url`, `sitemap.xml`, and `robots.txt`).
- `docs/robots.txt` and `docs/sitemap.xml` are already in place.
- Subpath safety: all asset/link references in `docs/` are relative (verified
  with a subpath serve test — zero 404s, search works).
- Recommendations from QA: `docs/404.html` (GitHub Pages serves it
  automatically for bad links) and `docs/.nojekyll` (harmless guard in case
  underscore-prefixed files appear later) — both added 2026-09-26.

## Docs site — QA fixes (2026-09-26)

Post-build integration and QA pass, all verified in headless Firefox:

- **Search modal ownership**: `docs.js` is the sole open/close owner
  (dispatches `docs:search-opened` / `docs:search-closed`); `search.js`
  only renders results. Fixed duplicate Ctrl+K handlers and the
  `.is-open` vs `.open` class mismatch.
- **CSS/markup contract**: added an integration layer to
  `docs/assets/css/docs.css` mapping the real `build.py` classes
  (`.tab-link`, `.nav-item`, `.search-box`, …) — the tab bar was rendering
  as a vertical bulleted list before this.
- **Search fixes**: heading `{id, text}` objects handled in scoring;
  `e.preventDefault()` on result click (fixed double navigation);
  styled result items (`.search-list`).
- **Copy-button CLS**: injected `.code-copy` buttons are now absolutely
  positioned (were unstyled/in-flow, shifting `<pre>` heights).
- **Double-escaping**: `build.py` escaped inline code twice
  (`&amp;amp;`) and TOC text twice — both fixed at the source.
- **Mobile overflow**: long inline `<code>` now wraps on ≤799px viewports
  (`.prose code` needed explicit inclusion for specificity); search kbd
  hint hidden on mobile.
- **Content merge**: stray `docs/parsing.md` + `docs/pipeline.md` merged
  into `docs/src/ingesting.md` per SITEMAP.md (parser tiers verified
  against `src/okfsmith/parsers/`), strays deleted.
- **Raw link text**: 7 `` `page.html` `` code spans converted to real links.
- **A11y**: focus trap + focus return for search modal/drawer, combobox
  ARIA, 3 contrast fixes (skip-link, kbd, code comments), 40px touch
  targets, drawer `visibility:hidden` when closed. 29/29 keyboard checks.
- **Security**: secrets scan clean; JSON-LD `</script>` breakout hardened.
- **SEO**: canonicals (were empty `href`), OG/Twitter, JSON-LD,
  `sitemap.xml` + `robots.txt` + `llms.txt` generated by `build.py`.
- **Perf**: largest page ~95 KB full load; DOMContentLoaded ~153–175 ms.
- Visual QA verdict: ~90% match to the Claude docs design language.
