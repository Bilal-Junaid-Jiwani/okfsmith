# GitHub Repo SEO — okfsmith (SEO Specialist 3/5)

Prepared for creation of public repo **Bilal-Junaid-Jiwani/okfsmith**.
Status: READ-ONLY task — no commits, no pushes. Everything below is copy-paste-ready for the release manager at creation time.

Keyword basis: `README.md` (cross-read 2026-09-26). No `.contract/seo/keyword-research.md` exists yet — keyword targets derived from README vocabulary + GitHub search/topic conventions. Coordinate with SEO specialists 1/2/5 (PyPI/docs discoverability) so terms stay consistent.

---

## 1. Repo short description (≤160 chars)

**Recommended (149 chars)** — copy-paste into the repo "About" field:

```
Forge messy PDFs, wikis, and Notion exports into Google's OKF v0.2 knowledge bundles — Python CLI with built-in validator and one-command MCP server.
```

Why this one: leads with the unique value ("messy" ingestion gap — nothing else claims it), names the standard (OKF v0.2), names the language (Python), and ends with two differentiators (validator, MCP). Includes the exact search terms people type: `pdf`, `okf`, `knowledge bundles`, `mcp`.

**Variant B (154 chars)** — for an audience that doesn't know OKF yet:

```
Python CLI that turns messy documents (PDFs, wikis, Notion exports) into Google's Open Knowledge Format v0.2 knowledge bundles, served to agents over MCP.
```

**Variant C (152 chars)** — "ingestion-first" positioning, good if competitors appear:

```
Ingestion-first CLI for Google's Open Knowledge Format: forge messy PDFs and wiki dumps into validated OKF v0.2 bundles with provenance and trust tiers.
```

**Variant D (154 chars)** — feature-dense, best for tool-listicles / awesome-lists:

```
Forge messy documents into Google's OKF v0.2 knowledge bundles: tiered PDF parsing, LLM extraction with provenance, §11 validator, one-command MCP server.
```

Note: the GitHub "About" description also feeds Google. Keep the primary; swap only if a variant tests better after 30 days.

---

## 2. Topic tags (max 20, ordered by value)

GitHub allows 20 topics. Ordered highest-value first (search volume × specificity × competition):

1. `okf` — own the standard's name; near-zero competition, exact intent
2. `knowledge-base` — high volume, direct fit
3. `rag` — high volume; users building RAG need exactly this ingestion step
4. `llm` — broad but the tool's core audience
5. `mcp` — fast-growing, exact-fit (one-command MCP server is a headline feature)
6. `cli` — how the tool is delivered
7. `python` — language filter people actually browse by
8. `pdf-parsing` — the #1 pain point named in the README
9. `pdf-to-markdown` — literal search query, low competition
10. `model-context-protocol` — the long-form of `mcp`; captures both spellings
11. `knowledge-graph` — `neighbors`/`graph`/`viz.html` features
12. `ai-agents` — the consumers of the MCP server
13. `document-processing` — the pipeline category
14. `notion` — named source format in README
15. `documentation-tool` — browsable category
16. `knowledge-management` — browsable category
17. `ollama` — local-LLM default; Ollama users search this topic
18. `information-extraction` — the extraction pipeline category
19. `open-source` — browsability signal
20. `nlp` — broad catchment, cheap slot

Copy-paste line for the release manager:

```
okf knowledge-base rag llm mcp cli python pdf-parsing pdf-to-markdown model-context-protocol knowledge-graph ai-agents document-processing notion documentation-tool knowledge-management ollama information-extraction open-source nlp
```

Do NOT use `knowledge-graph?` style guesses — topics must be exact strings. Avoid vanity topics with no search traffic (`forge`, `smith`).

---

## 3. README badge strategy

Keep the badge row **short and honest** — badge walls hurt credibility. Current badges (PyPI version, Python versions, license) are correct. At creation time, verify each badge URL resolves (the PyPI/license badges currently point at pages that don't exist yet — they'll 404 until release; that's expected, not a bug, but don't add more pre-release badges).

Recommended final set (in order):

1. `PyPI` version — conversion driver; keep
2. `Python` versions — keeps casual visitors from bouncing on compatibility doubt; keep
3. `License: Apache-2.0` — enterprise filter; keep
4. **Add after first CI run:** `CI` status badge (tests) — trust signal
5. **Add after first release:** `Downloads` (pepy) — social proof
6. **Optional:** `Code style: ruff` — only if enforced

Rules:
- Never add a badge for a metric that is zero or broken (empty "build: unknown" is worse than no badge).
- No badge for stars/followers — vanity, noisy.
- All badges in one row under the H1; no second badge row.
- Alt text on every badge image for accessibility.

---

## 4. Social preview (og:image) text spec

Upload at creation time: **Settings → General → Social preview → Upload image**.
Specs: **1280 × 640 px** PNG. Keep text in the central ~1000×440 safe area (GitHub crops edges on some surfaces). Dark background matching the project's dark-mode aesthetic; high contrast; no fine print.

Text layout (top → bottom):

```
okfsmith                      ← wordmark, largest, top-left or centered
Forge messy documents into    ← tagline, second largest
Google's OKF v0.2 bundles
parse → section → extract →   ← pipeline strip, small mono
link → emit → validate → serve
PDF · Wiki · Notion → MCP     ← source→serve shorthand, bottom
```

Design notes for whoever renders it:
- Font: Inter (matches the Inter-only rule from the Technovora lineage — keep brand-consistent).
- Accent color: pick one (amber/gold fits "forge") and use it only for the pipeline arrows and the wordmark.
- No logos you don't own. The OKF/Google wordmark: "Google's Open Knowledge Format" as plain text is fine; do not reproduce Google's logo.
- Export two versions (dark + light) if cheap; dark is primary.
- File name: `docs/social-preview.png` in-repo for reuse; upload the same file to GitHub settings.

Why this matters: the social preview is what shows on Twitter/X, LinkedIn, Discord, and in GitHub's own repo cards. It's the highest-ROI single image for launch distribution.

---

## 5. Release-notes SEO template

GitHub releases are indexed by Google and are the #1 long-tail surface ("okfsmith mcp windows install" will land here). Use this template for every release:

```markdown
## okfsmith vX.Y.Z — <plain-English headline with keywords>

One-paragraph summary: what changed and who it's for. Name the commands
touched (`okfsmith ingest`, `okfsmith mcp`) and the formats affected
(PDF, Notion export, wiki dump). 2–4 sentences, no jargon without explanation.

### Highlights
- <user-facing change, verb-first> (#PR)
- <user-facing change, verb-first> (#PR)

### Fixes
- <fix> (#PR)

### Docs
- <doc change> (#PR)

### Install / upgrade
pip install --upgrade okfsmith
# or
uvx okfsmith@X.Y.Z --help

Full changelog: vA.B.C...vX.Y.Z
```

Rules:
- Release **title** must contain `okfsmith vX.Y.Z` + a keyword-rich headline (titles are the indexed `<title>`).
- First paragraph must be human-readable (it becomes the meta description on shared links).
- Link every bullet to its PR/issue (`#123`) — internal links compound over time.
- Never leave "auto-generated" notes as the whole release; always write the summary paragraph.
- Tag format: `vX.Y.Z` (matches the template's install line).

---

## 6. Issue/PR template SEO notes

Issue and PR templates are not indexed meaningfully by search engines, so "SEO" here means **contributor discoverability and triage quality**, which indirectly drives stars:

- `.github/ISSUE_TEMPLATE/bug_report.md` — include fields: okfsmith version (`okfsmith --version`), OS, Python version, source file type (PDF/Notion/wiki), minimal repro. Structured fields → faster fixes → better reputation.
- `.github/ISSUE_TEMPLATE/feature_request.md` — fields: problem (as a user story), which pipeline stage (parse/section/extract/link/emit/validate/serve), willing to PR? (yes/no).
- Add a `good first issue` label at creation time and apply it to 3–5 small issues in week one — this is the single highest-ROI discoverability hack on GitHub (people browse that label).
- `PULL_REQUEST_TEMPLATE.md` — checklist: tests added, docs touched if user-facing, conventional-commit title. Keep it under 15 lines or contributors ignore it.
- `CONTRIBUTING.md` — link it from the PR template. One page: setup, test command, commit convention.
- Enable **Discussions** (Q&A category) at creation — keeps "how do I…?" out of issues, and discussion threads rank on Google for long-tail questions.
- Pin the contributing guide link in the repo's "About" website field? No — website field = PyPI page (conversion), not docs.

---

## 7. Pinned-issue launch plan

At creation time, open and **pin** this issue (pin: issue page → right sidebar → Pin). Title:

```
👋 Welcome to okfsmith — start here (roadmap, FAQ, how to help)
```

Body skeleton:

```markdown
**What is okfsmith?** One line: forge messy documents (PDFs, wikis, Notion
exports) into Google's OKF v0.2 knowledge bundles, served to agents over MCP.

**60-second try:** pip install okfsmith → okfsmith init ./kb → ingest → validate → mcp

**Roadmap to 1.0** (from README): first PyPI release · wider Tier 2/3 scan
coverage · incremental re-ingest with LLM-adjudicated dedup · richer lints.
Explicit non-goals: no vector DB, no attestation runtime.

**How to help:** good first issues (link) · report messy docs that break parsing
(attach samples) · star if useful — it helps others find the project.

**FAQ** (grow this): Is my data sent anywhere? (No — Tier 1 is local.) Which
models? (Local Ollama default; hosted via env vars.) OKF v0.1? (v0.2 only.)
```

Why a pinned issue: it's the repo's living billboard — every visitor sees it, it accumulates the FAQ that would otherwise become duplicate issues, and the roadmap section converts visitors into watchers.

Week-one additions: unpin only when a real discussion (e.g., "v1.0 tracking") earns the slot.

---

## 8. GitHub trending reality check (be honest)

What GitHub trending **actually** is: a velocity ranking — stars per unit time, segmented by language, over ~24h–7d windows. There is no submission form and no editorial board.

What actually drives it:
1. **Real distribution.** A launch post that reaches the right 5,000 people (r/Python, Hacker News "Show HN", relevant Discords, the MCP/AI-agent community, awesome-lists) beats everything. Trending is a lagging indicator of distribution, not a lever.
2. **Star velocity in a tight window.** ~100–300 stars in 24–48h can trend for Python on a quiet day; there is no fixed threshold and gaming it is detectable.
3. **A README that converts in 30 seconds.** The current README does this well (quickstart above the fold, honest comparison table). Keep it.
4. **Awesome-list inclusion** (`awesome-python`, `awesome-mcp-servers`, `awesome-llm` lists) — durable, compounding traffic; PR these in week 2–4.

What does NOT work / is harmful:
- Star-buying services: botted stars get the repo flagged, kill credibility with the exact audience (developers) you need, and GitHub removes inauthentic stars.
- "Star for star" threads: zero retention, signals desperation.
- Spamming issues/PRs on other repos for visibility: fastest way to get blocked by maintainers.

Honest bottom line: most good repos never trend. Trending is a lottery ticket; **PyPI downloads and awesome-list placement are the compounding assets**. Optimize for those.

---

## 9. Realistic expectations (required — no #1 guarantees)

- **No #1 guarantees, of any kind.** Nobody can promise GitHub trending, a Google #1 ranking, or a star count. Anyone selling that is selling fraud.
- **OKF is a niche standard (for now).** Search volume for "okf" / "open knowledge format" is small today. That's an advantage (near-zero competition — you can own every query) and a limit (ceiling is bounded by the standard's adoption, which Google, not you, drives).
- **Realistic 90-day outcomes** if distribution is executed: a few hundred stars, steady PyPI downloads in the low thousands/month, inclusion in 2–5 awesome-lists, and owning page 1 for "okf cli", "okf python", "pdf to okf", "mcp knowledge base cli". These are achievable and valuable.
- **The honest conversion funnel is:** Google/GitHub search → README quickstart → `pip install` → bundle built. Every SEO action here serves that funnel; anything that doesn't (vanity badges, star begging) is cut.
- **Biggest risk to SEO isn't ranking — it's abandonment signals.** An empty issue tracker, no commits for months, and unanswered questions kill conversion harder than any ranking factor. The maintenance cadence IS the SEO strategy after launch.

---

## 10. Creation-time checklist (for the release manager)

Run top-to-bottom at repo creation. Checkboxes are literal — check them off.

**Repo settings**
- [ ] Create public repo `Bilal-Junaid-Jiwani/okfsmith` (public from minute one — private-then-public loses the "new repo" freshness window)
- [ ] About → description: paste the recommended description (§1)
- [ ] About → website: `https://pypi.org/project/okfsmith/` (after PyPI release; leave blank before — no dead links)
- [ ] About → topics: paste the 20-topic line (§2)
- [ ] Settings → Social preview: upload `docs/social-preview.png` (1280×640, §4)
- [ ] Features: enable **Issues**, **Discussions** (Q&A category); keep Projects/Wiki off until needed
- [ ] License: confirm `LICENSE` (Apache-2.0) is detected — the license badge in the About sidebar depends on detection
- [ ] Default branch: `main`; branch protection (require PR + tests) before accepting contributions

**Content**
- [ ] README badges resolve (PyPI + license badges 404 until release — expected; re-check post-release)
- [ ] `.github/ISSUE_TEMPLATE/` (bug, feature) + `PULL_REQUEST_TEMPLATE.md` + `CONTRIBUTING.md` committed
- [ ] `good first issue` label created; 3–5 issues labeled in week one
- [ ] Pinned welcome issue opened + pinned (§7)

**Release**
- [ ] First release `v0.1.0` (or chosen number) using the release-notes template (§5) — never ship auto-generated-only notes
- [ ] Tag format `vX.Y.Z` everywhere

**Distribution (week 1–4, the actual trending lever)**
- [ ] Show HN post drafted (demo: messy PDF → validated bundle → MCP query, all local)
- [ ] r/Python + r/LocalLLaMA launch posts (follow each subreddit's self-promo rules)
- [ ] PRs to awesome-lists: `awesome-python`, `awesome-mcp-servers`, any `awesome-llm`/`awesome-rag` lists
- [ ] PyPI page live with the README as long description (coordinates with PyPI SEO specialist)

**Don't**
- [ ] Don't buy stars, don't star-trade, don't spam other repos
- [ ] Don't promise rankings or trending anywhere in public copy
- [ ] Don't add badges for zero/broken metrics
