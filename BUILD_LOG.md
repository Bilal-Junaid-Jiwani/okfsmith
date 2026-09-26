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
- **Dedup:** SHA-256 source dedup + normalized-title/resource match + embedding similarity, LLM adjudicates merges.
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
