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
