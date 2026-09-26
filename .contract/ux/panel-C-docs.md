# UX Panel C — Docs & Onboarding Verdict: okfsmith

**Panel:** 3 senior docs/onboarding designers, one voice.
**Scope:** `docs/OVERVIEW.md`, `examples/bundles/` (cs-curriculum, okf-primer),
the 5-minute new-user journey, missing guides, skill-pack discoverability.
**Bar:** Stripe / Vercel / uv docs onboarding. Best-in-class or nothing.
**Date:** 2026-09-26. **Mode:** read-only audit (no commits, no pushes).

## 1. VERDICT: CHANGES-REQUIRED

The docs read well but describe a product that does not exist yet. The README's
60-second quickstart fails at **step 1** (`pip install okfsmith` — package is not
on PyPI; the badge links 404) and at **step 2** (`okfsmith init` → `No such command`
— verified live: the installed CLI is a stub with only `--version`; the 7
documented commands live unmerged in `/tmp/wt-cli`). A new user following the
docs verbatim gets a broken experience in under a minute. That is the single
disqualifying fact. Everything else is fixable; this must be fixed first.

The example bundles are genuinely good onboarding material (well-written,
honest fictional framing, cited claims, all three trust tiers exercised, links
all resolve, both pass the §11 hard rules) — but they carry two spec-accuracy
defects that would fire warnings on the real validator and one wrong-source
citation that contradicts the project's own locked spec decisions.

The skill pack (`okfsmith-build`) is well-crafted agent documentation (decision
table, gotchas, one-level references) — and is completely undiscoverable: it
lives only in the `/tmp/wt-skill` worktree, is not in the repo, and is linked
from nowhere.

## 2. Findings

Severity scale: **BLOCKER** (ship-stopper) · **HIGH** (v1 must-fix) ·
**MEDIUM** (v1 should-fix) · **LOW** (polish).

| Sev | Location | Issue | Concrete fix spec |
|---|---|---|---|
| BLOCKER | `README.md` → "60-second quickstart" | End-to-end non-functional. `pip install okfsmith`: package not on PyPI (roadmap confirms "first PyPI release" is future; no PyPI search hit; badges link to 404s). `okfsmith init` / `ingest` / `validate` / `mcp`: `No such command 'init'` verified live — `src/okfsmith/cli/app.py` is an explicit stub ("The CLI engineer adds commands later"). Commands exist only in unmerged `/tmp/wt-cli`. | (1) Do not document commands that don't exist in the tree. Until release, the quickstart must be: `git clone https://github.com/Bilal-Junaid-Jiwani/okfsmith` → `pipx install -e .` (or `uvx --from git+https://…`) → the merged commands. (2) Add a docs CI test (`docs-test` job) that executes every shell block in README + quickstart verbatim — uv-style: docs are code. (3) Badge links: either publish to PyPI first, or replace badges with "pre-release — install from source" until then. Never ship a 404 badge. |
| BLOCKER | repo root: `skills/` missing | README "Features" advertises a "SKILL.md pack" that is not in the repo. The pack exists only at `/tmp/wt-skill/skills/okfsmith-build/` (SKILL.md + 3 references + `scripts/validate.py`). Nothing links to it; no install/discovery path exists. | Merge the skill into `skills/okfsmith-build/` on main. Add to README Features a real link + install snippet (`cp -r skills/okfsmith-build ~/.agents/skills/` or agent config path), plus a new `docs/skill-pack.md` (see TOC). Consider agentskills.io registry submission for discoverability. |
| BLOCKER | `README.md` CLI reference → `docs/OVERVIEW.md` | Broken internal promise: "See docs/OVERVIEW.md for the pipeline each command drives" — but OVERVIEW.md contains **zero** command→stage mapping. A new user cannot learn which command runs which stage. | Add a command→stage table to OVERVIEW.md: `init`→(scaffold), `ingest`→stages 1–6, `validate`→7, `mcp`→8, `graph`→8, `list`/`read`→bundle I/O. |
| HIGH | `examples/bundles/` — all concepts using `stale_after` | Every `stale_after: 2027-09-26` (5 files: `cs-curriculum/courses/cs101.md`, `topics/recursion.md`, `resources/sicp.md`, `okf-primer/concepts/trust-tiers.md`, `concepts/conformance.md`) is a **bare date with no UTC offset**. Locked spec decisions §5-intro/W011 require ISO 8601 **with explicit UTC offset**; the real validator would emit W011 on the project's own showcase bundles, contradicting `examples/bundles/README.md`'s "check OKF §11 conformance" cleanliness claim. | Change all to `2027-09-26T00:00:00Z`. |
| HIGH | `examples/bundles/okf-primer/concepts/frontmatter.md` (§ "Lifecycle") | Teaches the wrong format: "`stale_after: YYYY-MM-DD`" — a bare date — which is exactly the W011 violation above. Onboarding material teaches users to produce warnings. | Rewrite line as: `` `stale_after: 2027-09-26T00:00:00Z` `` (ISO 8601 with explicit UTC offset; a concept is stale when `now >= stale_after` in UTC). |
| HIGH | `examples/bundles/okf-primer/concepts/*.md` — `sources[].id: spec-md` | Cites `https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md` — but `.contract/spec_decisions.md` **locks** the canonical source as the live SPEC.md in `GoogleCloudPlatform/open-knowledge-format` and calls the `knowledge-catalog/okf/` copy a "FROZEN SNAPSHOT — ignore it." The format-explaining-itself bundle cites the snapshot the project tells implementers to ignore. | Repoint `spec-md` source to the canonical repo: `https://github.com/GoogleCloudPlatform/open-knowledge-format` SPEC.md. Keep `spec-repo` as is (already correct). |
| HIGH | docs: missing `docs/troubleshooting.md` | No troubleshooting guide exists. Predictable new-user failures have no documented path: "No such command" (stale install vs new docs), Ollama not running / connection refused, ingest producing zero concepts, validate E001–E004 with no fix guidance, PEP 668 `externally-managed-environment` on `pip install`. | New page: symptom → cause → fix table, including per-code fixes for E001–E004 and the top 8 W-codes (link to `docs/validator.md`). |
| HIGH | docs: missing "no LLM available" path | README promises "Tier 1 parsing is local and free; no API keys needed" and "LLM features default to a local Ollama model" — but `ingest` runs 2-pass LLM extraction; there is **no documented path** for a user with no Ollama and no API keys. The parsing slice's `ingest_no_llm` contract exists (BUILD_LOG) but is undocumented. Users will hit a wall with no explanation. | New `docs/llm.md` (see TOC) with a first-class "No LLM? Parse-only mode" section: what works without a model (parse → section → emit as draft concepts), exact command/flags, and what is deferred until a model is available. |
| HIGH | docs: missing Notion export how-to | README lists Notion exports as a headline input ("PDFs, markdown, wiki dumps, Notion exports"), but no in-repo guide exists. The knowledge lives in `/tmp/wt-skill/.../references/parsing-tiers.md` (Notion zip handling, page-ID suffix stripping) — unmerged and unlinked. | Merge `references/parsing-tiers.md` content into new `docs/parsing-tiers.md` with a step-by-step "Export from Notion → ingest" walkthrough (Export → Format & include content → zip → `okfsmith ingest`). |
| HIGH | `docs/OVERVIEW.md` — stage explanations | For the stated student reader (BUILD_LOG: "written for the project owner (a student)"), the diagram is clear but the stage text is jargon-dense on first use: "contextual situating prefix", "FastMCP stdio", "claim infidelity", "sidecar", "bare-mapping" (in linked contract). No per-stage input/output contract — a student can't picture what data enters and exits each stage. | Per stage add one line: **In → Out** (e.g. Stage 4: "In: sections with lineage · Out: concept JSON drafts with `[^source-id]` footnotes"). Add a 6-term plain-language glossary. Add one walkthrough paragraph following a single 10-page PDF through all 8 stages. |
| MEDIUM | `examples/bundles/README.md` → "Validate" | Validation instructions assume an installed `okfsmith validate` (doesn't exist in tree). New users can't run the flagship demo command. | Once skill merges: document the stdlib fallback first — `python3 skills/okfsmith-build/scripts/validate.py examples/bundles/cs-curriculum` — then the `okfsmith validate` form. |
| MEDIUM | docs: missing `docs/validator.md` | E001–E004 / W001–W015 are locked in `.contract/` (implementer doc) but no user-facing reference exists. uv/Stripe-class docs give every error code its own fix page. Users hitting `E002 empty-type` get no docs hit. | New page: per code — what fires, minimal repro, how to fix, spec citation. This is the single highest-leverage docs addition for support-load reduction. |
| MEDIUM | `README.md` → Configuration | `OKFSMITH_MODEL` default is "local Ollama model" — no model name, no pull command (`ollama pull <model>`), no port, no "is Ollama running?" check. A new user can't act on it. | Name the default model, give the exact `ollama pull` + verify commands, and the env-var override examples for Anthropic/OpenAI. |
| MEDIUM | `README.md` → install (PEP 668) | `pip install okfsmith` fails on modern Debian/Ubuntu/Fedora Python with `externally-managed-environment` (observed live during this audit). Docs recommend the one install path most likely to error for beginners. | Recommend `pipx install okfsmith` (post-PyPI) / `uvx okfsmith` for one-shot runs; document the `--break-system-packages` escape hatch only as a footnote. |
| MEDIUM | `docs/OVERVIEW.md` — freshness | No version/date stamp, no "verified against OKF spec v0.2 (2026-09-26)" line. Stripe-class docs carry freshness signals so readers can trust them. | Add header stamp: spec version, last-verified date, and a pointer to `.contract/spec_decisions.md` as the implementer source of truth. |
| LOW | `README.md` → badges | PyPI/Python/License badges link to `pypi.org/project/okfsmith` (404) and repo license path. Verify `github.com/Bilal-Junaid-Jiwani/okfsmith` is public before v1; dead badges are worse than no badges. | Gate badges on publish; link-check in docs CI. |
| LOW | Honesty of examples | Positive: `cs-curriculum` is explicitly framed as fictional demo content with real cited claims; `grace-hopper.md` carries an explicit "Trust note" and `status: draft`. This matches the project's honest-placeholder standard — keep it. Minor: `examples/bundles/README.md` should state the fiction boundary in one line at the top (it does, mid-paragraph — promote it). | Move "fictional curriculum; course sequencing is illustrative" to the first sentence of the cs-curriculum section. |

### What is already good (keep)

- `docs/OVERVIEW.md` pipeline diagram: numbered, strictly-ordered, one screen. Rare for a v0.1.
- Example bundles as pedagogy: `okf-primer` ("the format explaining itself") is an excellent onboarding device; footnote attribution `[^id]`→`sources[].id` is demonstrated, not just described; all three trust tiers are exercised; every cross-link resolves (verified mechanically — zero broken links, zero unresolved footnotes).
- Skill pack content quality: decision table ("when NOT to use" incl. honest `okf-cli` redirect), gotchas section, and the stdlib-only `validate.py` fallback are exactly right for agent consumers.
- README "How it compares" table: honest framing ("clean markdown in → okf-cli is fine") builds trust; keep this tone everywhere.

## 3. Proposed `docs/` table of contents for v1

Every file ships with a freshness stamp (spec v0.2, last-verified date). All shell
blocks are executed verbatim by docs CI.

| File | One-line purpose |
|---|---|
| `docs/index.md` | Docs landing: what okfsmith is, who it's for, 3 paths (5-min quickstart / CLI reference / agent skill pack). |
| `docs/quickstart.md` | The 5-minute script below — install → init → ingest → validate → mcp, tested in CI. |
| `docs/install.md` | pipx vs pip vs uvx vs source install; PEP 668 note; `[mcp]`/`[ocr]` extras; `okfsmith --version` smoke test. |
| `docs/pipeline.md` | Revised OVERVIEW: 8-stage diagram + per-stage In→Out contracts + command→stage map + failure modes + student glossary. |
| `docs/concepts.md` | OKF v0.2 in okfsmith terms: bundle layout, concept IDs, frontmatter families, trust tiers, linking, index/log — companion to the `okf-primer` bundle. |
| `docs/commands.md` | Full CLI reference, one section per command with examples and exit codes (`okfsmith <cmd> --help` parity). |
| `docs/validator.md` | E001–E004 / W001–W015: what fires, minimal repro, how to fix, spec citation — the error-code docs. |
| `docs/parsing-tiers.md` | Tier 1/2/3 policy, scan-escalation rules, per-format table, Notion-zip how-to. |
| `docs/llm.md` | Extraction config: Ollama default (named model + pull command), env-var hosted models, privacy notes, and the first-class **no-LLM parse-only path**. |
| `docs/mcp.md` | Serving: stdio server, tool reference (`search`/`get`/`list`/`neighbors`/`index`), client configs (Claude Code, Cursor, Copilot, Gemini CLI), read-only guarantee. |
| `docs/skill-pack.md` | What `skills/okfsmith-build/` is, where it lives, how agents/humans install it, agentskills.io format notes. |
| `docs/troubleshooting.md` | Symptom → cause → fix table; install skew; Ollama issues; validate codes quick-fix. |
| `docs/glossary.md` | Plain-language definitions: contextual situating prefix, FastMCP, stdio, sidecar, trust tier, attestation, orphan, stub. |
| `docs/faq.md` | okfsmith vs okf-cli vs Go/Rust tools; why no vector DB; why no PyMuPDF (AGPL); why broken links are warnings. |
| `docs/changelog.md` | Pointer to root CHANGELOG.md (create at release). |
| `examples/bundles/README.md` | Revise per findings: stdlib-first validate instructions, `stale_after` fix, canonical spec source, fiction boundary up top. |

## 4. Five-minute quickstart script (v1 target)

> Docs-CI executes this verbatim on Linux/macOS/Windows. Pre-release: replace
> step 0 with `git clone … && pipx install -e .` until the first PyPI publish.

```bash
# 0. Install (pick one) — 60 seconds
pipx install okfsmith            # recommended: isolated CLI
# uvx okfsmith --help            # one-shot, no install

okfsmith --version               # expect: okfsmith 0.1.0

# 1. Scaffold a bundle — 15 seconds
okfsmith init ./kb               # creates index.md + log.md scaffold

# 2. Ingest a messy document — ~2 minutes (Tier 1: local, free, no keys)
okfsmith ingest ./kb docs/quarterly-report.pdf
# → parses → sections → extracts concepts (Ollama default; see docs/llm.md
#   for the no-LLM parse-only path) → links → emits markdown + frontmatter

# 3. Validate against OKF §11 — 10 seconds
okfsmith validate ./kb
# 42 concepts · 0 errors · 3 warnings
# errors = E001–E004 (must fix) · warnings = W001–W015 (advisory, see docs/validator.md)

# 4. Serve it to your agent — 30 seconds
okfsmith mcp --bundle ./kb      # FastMCP over stdio; tools: search get list neighbors index
# Point any MCP-capable agent at the stdio server (configs: docs/mcp.md).
# Humans: okfsmith graph ./kb → open viz.html in a browser.

# Stuck? docs/troubleshooting.md · full reference: docs/commands.md
```

---

**Panel C footer — supervision note.** This verdict is **CHANGES-REQUIRED**.
Panel C supervises every builder iteration on docs/onboarding: we will re-review
after each builder pass and withhold approval until (a) the quickstart runs
verbatim end-to-end in docs CI, (b) the skill pack is merged and linked, and
(c) the example bundles pass the full E/W validator with zero warnings. We
re-review until APPROVED — best-in-class or nothing.
