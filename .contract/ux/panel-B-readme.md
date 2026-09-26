# UX Panel B — README-as-landing-page audit

**Auditors:** 3 senior content/landing-page designers, one voice · **Date:** 2026-09-26
**Scope:** `~/workspace/projects/okfsmith/README.md` vs. best-in-class open-source READMEs (uv, ruff, bat, starship, httpie)
**Method:** line-by-line read; every quickstart command cross-checked against `pyproject.toml` (`[project.scripts]` → `okfsmith = "okfsmith.cli.app:app"`) and the real CLI surface on the `feat/cli` branch worktree (`/tmp/wt-cli/src/okfsmith/cli/commands.py`, wired via `okfsmith/cli/__init__.py`); external claims spot-checked (PyPI, LiteParse).

## VERDICT: CHANGES-REQUIRED

**Counts:** 3 blockers · 5 majors · 6 minors.

The README reads well and the "Why okfsmith" gap table plus the honest-framing paragraph are genuinely good. But it fails the panel's bar on the single most important README job: **the quickstart does not work.** The centerpiece `ingest` command has the wrong signature, the install path points at a PyPI page that doesn't exist, and the `graph` row documents behavior the code doesn't have. A best-in-class README never makes the reader's first 60 seconds fail. Fix the blockers, apply the majors, and this becomes a strong page.

---

## Findings

| # | Severity | Section | Issue | Concrete rewrite spec |
|---|---|---|---|---|
| B1 | blocker | 60-second quickstart, CLI reference | `okfsmith ingest ./kb docs/quarterly-report.pdf` is **wrong**. Real signature (verified in `/tmp/wt-cli/.../cli/commands.py:118`): `ingest(source: Argument, --bundle: Option REQUIRED, --model, --no-llm, --recursive)`. The README's positional `./kb` will error out. | Change to `okfsmith ingest docs/quarterly-report.pdf --bundle ./kb`. Add `--bundle` to the CLI reference row for `ingest`; add its real options (`--no-llm`, `--model`, `--recursive`) in one short line. See rewritten quickstart below. |
| B2 | blocker | Badges, quickstart install step | `pip install okfsmith` and `uvx okfsmith mcp` **cannot work**: the package is not on PyPI (name verified free, never published) and the GitHub repo does not exist yet. All three badges 404 (PyPI version, Python versions, license-via-GitHub-API). A dead install step in line 1 of the quickstart destroys trust instantly. | Add a pre-release banner (spec below). Replace the install step with from-source install: `git clone … && cd okfsmith && pip install -e .[mcp]`. **Remove all three badges until first PyPI/GitHub release**; re-add version + CI badges at publish time. A 404 badge is worse than no badge. |
| B3 | blocker | CLI reference (`graph` row) | "`okfsmith graph ./kb` — Render `viz.html`" is **false**. Verified default: `--format text` prints to stdout; `viz.html` requires `--format html` (default output `<bundle>/viz.html`, overridable with `--output`). | Row must read: `okfsmith graph ./kb --format html` → "Render `<bundle>/viz.html` (also: `text`, `json`, `mermaid`)". See rewritten quickstart below. |
| M1 | major | Hero (first 5 lines) | Hook assumes the reader knows OKF. uv/ruff/bat lead with a plain-language problem; here line 1 is the name, lines 2–4 are badges, and the tagline — "Forge messy documents into Google's Open Knowledge Format (OKF) v0.2 knowledge bundles" — is jargon-first. A newcomer bounces before learning what problem this solves. | Rewrite per spec below: problem-first one-liner ("Turn messy documents into agent-ready knowledge."), then the OKF sentence as the *how*. Keep it to 2–3 lines before the quickstart; move the current explanatory paragraph under the quickstart or into "Why okfsmith". |
| M2 | major | Whole README | No pre-release framing: SKILL.md pack, MCP server, 2-pass LLM extraction, and the `ingest`/`validate`/`graph`/`mcp` commands are presented as shipped, but on `master` the CLI has only `--version` (commands live on unmerged `feat/cli`; `validate`/`graph`/`mcp` lazily load `okfsmith.validate`, `okfsmith.viz`, `okfsmith.mcp_server`, none of which exist yet). Best-in-class pre-release READMEs (e.g. early uv) mark what's coming. | Add the pre-release banner from the spec below; tag aspirational rows with a `🚧` or "(coming)" marker until the slices merge. Never let the README get ahead of the default branch. |
| M3 | major | Quickstart (`validate` output) | The sample output `# 42 concepts · 0 errors · 3 warnings` is **fabricated**: `_print_report` in `commands.py` prints `Errors`/`Warnings` tables — no concept count, no `·` summary line. Sample output that doesn't match real output teaches users to distrust the docs. | Show real output shape (Errors/Warnings tables) or drop the sample-output comment and instead add one line describing what success looks like (`exit 0`, warnings listed). |
| M4 | major | Features | Seven dense, jargon-heavy bullets ("contextual situating prefix", "critic pass verifies contradictions") with zero concrete example. ruff/bat sell features with before/after snippets; here the reader never sees what a forged concept *looks like*. | Add one compact before→after example under Features: 3 lines of messy PDF text → the emitted markdown file with frontmatter (`type`, `sources[]`, trust tier). Cut each bullet to one line + move mechanism detail to `docs/OVERVIEW.md`. |
| M5 | major | How it compares | The "Go / Rust OKF tools" column is unverifiable (no tool named, all cells "varies") and "Graphify-style tools" is hand-wavy. The panel verified `okf-cli` is real (PyPI `okf-cli` 0.6.1, `okf bundle/validate/list/read`) and the description of it is accurate — keep that column. Vague columns read as strawmen and undermine the otherwise honest framing paragraph. | Either name the actual Go/Rust tools with links, or drop that column and keep `okfsmith` vs `okf-cli` vs "hand-rolled scripts" (the real alternative for messy PDFs). Delete every "varies" cell — a comparison cell must contain a fact. |
| m1 | minor | License | `[LICENSE](https://github.com/Bilal-Junaid-Jiwani/okfsmith/blob/main/LICENSE)` 404s — the repo doesn't exist. | Use the relative link `[LICENSE](LICENSE)`; it works on disk and on GitHub after creation. |
| m2 | minor | Whole page | No table of contents; at ~7.5 KB with 12 sections, skimmability suffers on mobile. | Add a 10-line TOC after the quickstart (uv-style, no sub-bullets). |
| m3 | minor | Features (`graph` bullet) | `okfsmith graph` is the only visual feature and there's no screenshot, even a placeholder ASCII/`<img>` slot. | Add a screenshot of `viz.html` once it exists; until then, one sentence describing what the graph view shows. |
| m4 | minor | Configuration | "Zero config to start" overclaims: default `ingest` runs 2-pass LLM extraction against a **local Ollama model**, which requires Ollama installed, running, and a model pulled. That's real setup. | One line: "LLM extraction needs Ollama running locally (`ollama pull <model>`); `--no-llm` gives deterministic sectioning with no model at all." |
| m5 | minor | Trust tiers | `human-reviewed` is "stamped on review" but no `review`/`verify` command exists in the CLI surface — the reader can't reach the top tier. | Either document the manual path (edit `verified:` in frontmatter) in one line, or mark the tier "🚧 CLI support coming". |
| m6 | minor | Quickstart | Reader never sees what a bundle *is*: no output tree. httpie/bat show the artifact. | After `init`, show a 6-line `tree ./kb` (`index.md`, `log.md`, `concepts/…`) so the abstract "bundle" becomes concrete. |

### What the README already does well (keep)

- The "Why okfsmith" gap table names the white space precisely; the `parse → section → extract → link → emit → validate → serve` pipeline line is excellent.
- The honest-framing paragraph under the comparison table ("clean markdown in → `okf-cli` is fine…") is exactly the tone that builds trust — expand this instinct, don't cut it.
- Configuration table is disciplined (env-only keys, "never from files, flags, or the repo").
- "What v1 will **not** do — by design" is a best-in-class trust signal. Keep and keep honest.

---

## Rewritten hero + quickstart (verbatim — builder pastes as-is)

> Assumes the `feat/cli` command surface (verified signatures). Do not paste until B2's install path is true; the pre-release banner covers the gap until PyPI publish.

```markdown
# okfsmith

> **Pre-release:** okfsmith is under active development and not on PyPI yet — install from source below. Commands reflect the current CLI; `🚧` marks slices still landing.

**Turn messy documents into agent-ready knowledge.**

okfsmith is a Python CLI that forges PDFs, wiki dumps, and Notion exports — the 200-page reports with broken reading order that no other tool handles — into Google's Open Knowledge Format (OKF) v0.2 bundles: plain markdown files with YAML frontmatter. Every concept carries provenance (`sources[]`), a trust tier, and lifecycle metadata; a built-in §11 validator checks every bundle; one command serves it to any MCP-capable agent.

## 60-second quickstart

```bash
# install from source (PyPI release coming)
git clone https://github.com/Bilal-Junaid-Jiwani/okfsmith
cd okfsmith
pip install -e .[mcp]

# start a bundle
okfsmith init ./kb
# ./kb
# ├── index.md
# ├── log.md
# └── concepts/

# ingest a messy PDF — Tier-1 parsing is local and free, no API keys.
# Needs Ollama running for LLM extraction; add --no-llm for
# deterministic sectioning with no model at all.
okfsmith ingest docs/quarterly-report.pdf --bundle ./kb

# validate against OKF §11 (hard rules + advisory lints)
okfsmith validate ./kb

# browse the concept graph in your browser
okfsmith graph ./kb --format html   # writes ./kb/viz.html

# serve it to your agent over MCP (stdio)
okfsmith mcp --bundle ./kb
```

Point any MCP-capable agent at the stdio server — tools are `search`, `get`, `list`, `neighbors`, `index` — and every answer traces back to `sources[]` in the bundle. See [docs/OVERVIEW.md](docs/OVERVIEW.md) for the `parse → section → extract → link → emit → validate → serve` pipeline behind these commands.
```

**Badge spec (applies with this paste):** delete the three existing badges. Re-add at first release: PyPI version, Python versions (3.10+), CI status, license — all pointing at live pages.

---

## Re-review commitment

UX Panel B supervises **every** builder iteration of this README. The builder applies the findings table above (blockers first), then returns the revised `README.md`; the panel re-reviews against the same best-in-class bar (uv, ruff, bat, starship, httpie) and the same command-verification method (`pyproject.toml` entry points + real CLI signatures). **This loop repeats until the panel returns APPROVED — no iteration ships without it.**
