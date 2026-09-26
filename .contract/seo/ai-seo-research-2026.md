# AI SEO / Discoverability Market Research (2026)

**Author:** SEO Specialist 1 (AI-SEO market research) — okfsmith senior team
**Date:** 2026-09-26
**Scope:** How AI discoverability ("AI SEO" / GEO) actually works in the market right now, grounded in evidence. What is real vs hype. Ranked legitimate levers for okfsmith (Apache-2.0 Python CLI converting messy documents into Google OKF v0.2 knowledge bundles; PyPI name "okfsmith" free; future repo `Bilal-Junaid-Jiwani/okfsmith`).

Related sibling research in this directory: `github-seo.md`, `pypi-seo.md`, `keyword-research.md` (colleagues' files — do not duplicate; this file covers the AI-discovery angle).

---

## 1. What "AI SEO" means in 2026 (and how AI assistants actually discover tools)

AI assistants surface developer tools through **four distinct channels**, and each needs a different lever:

1. **Training-data recall** — the model memorized it during pretraining. Lagged (months), probabilistic, and favors things discussed repeatedly across many sources. You cannot optimize this directly; you earn it by being *talked about* across the ecosystem.
2. **Live search / browsing (RAG)** — agents that call a search tool mid-task. This closes the recency gap: "an agent that recommends a product... is repeating whatever was true when its training data was collected... that gap closes only when the agent can call a search tool mid-task." Everything that makes you visible to Google/crawlers (crawlable docs, fast fresh pages, structured data) feeds this channel.
3. **Registries and capability catalogs** — the new discovery layer. On 2026-06-17 Google, Microsoft and GitHub announced **Agentic Resource Discovery (ARD)**, an open spec (v0.9 draft, Apache-2.0, at agenticresourcediscovery.org): providers host an **`ai-catalog.json`** at a well-known path on their domain describing MCP servers, skills, APIs, agents; registries return ranked matches for natural-language intent. First shipping implementation: **GitHub Agent Finder** in Copilot. Also: the **GitHub MCP Registry** ("the npm for MCP servers", launched Jan 2026). If okfsmith ever ships an MCP server or an agent **Skill** (SKILL.md), registering it in these catalogs is the legitimate path to agent discoverability.
4. **Direct recommendations in agent context** — skills dirs, awesome lists, tldr pages, docs that coding agents fetch on demand (Cursor, Claude Code, Copilot read `llms.txt` when indexing docs sites on demand).

**Key 2026 shift:** AI citations are *decoupling* from classical rankings. Ahrefs (2026): **only 38% of Google AI Overview citations now come from top-10 ranking pages, down from 76% in mid-2025**. Ranking well no longer guarantees being cited by AI.

### GEO: what is real (evidence-based)

"Generative Engine Optimization" comes from the academic paper GEO: Generative Engine Optimization (Aggarwal et al., Princeton/Georgia Tech/Allen AI/IIT Delhi, KDD 2024, arxiv.org/abs/2311.09735), which found up to **~40% visibility improvements** in generative-engine responses from content tactics. Independent 2026 evidence supports these concrete tactics, strongest first:

1. **Build on solid traditional SEO first.** GEO is a layer on top, not a replacement. Content a crawler can't reach or parse is invisible to both. (GEO vendor playbook, 2026: "hybrid approach wins.")
2. **Answer-first structure, query fan-out coverage.** A generative engine decomposes a question into sub-queries ("fan-out") and retrieves separately for each. Content that only answers the literal headline question is invisible to most of the fan-out. For okfsmith: answer the sub-questions — "convert PDF to structured knowledge bundle", "OKF v0.2 format", "Google knowledge format CLI", "RAG document preprocessing tool", etc.
3. **Cite authoritative sources, name experts, use specific statistics, confident declarative prose.** Synthesized answers favor content that itself demonstrates sourcing discipline and extractable, citable claims.
4. **Own comparison and "best-of" queries.** This is where engines lean hardest on external content — synthesizing a genuine comparison from scratch is exactly what an LLM benefits from an authoritative existing source for. A legitimate `okfsmith vs pandoc / vs MarkItDown / vs unstructured / vs LangChain loaders` comparison page is high-value.
5. **Seed the sources the engines already trust.** Presence across Wikipedia/Reddit/LinkedIn/HN/St-ack Overflow correlates with citation; brand search volume correlates with citations more than raw backlink count.
6. **Freshness and length.** ChatGPT shows the strongest recency preference of any engine (most-cited pages updated within the past 30 days). 53% of pages cited in AI Overviews are under 1,000 words (Ahrefs). FAQ schema materially improves citation rates (vendor study: 41% vs 15% with/without FAQPage schema).
7. **Measurable as AI citation share** across engines — start tracking which engines cite the docs/pages now (free tools exist; vendors sell tracking across 20+ platforms and 14 LLMs, but a manual monthly check is fine at our scale).

### llms.txt: the honest 2026 verdict

This is the most overhyped lever in AI SEO. Evidence:

- **Adoption up, consumption near zero.** Originality.ai (Jul 2026): llms.txt files grew ~8.8× in a year (~4,000 in Jun 2025 → ~36,000 by May 2026). Ahrefs server-log study of ~137,000 domains: **97% of llms.txt files received zero requests in May 2026**; genuine AI retrieval bots were ~1% of the requests that did occur.
- **Major crawlers skip it.** GPTBot, ClaudeBot, PerplexityBot do not fetch llms.txt. Google's John Mueller compared it to the keywords meta tag; Google's May 2026 AI-optimization guidance explicitly says it is **not needed** for AI Overviews/AI Mode.
- **No ranking/citation effect.** SE Ranking (~300k domains): no correlation between having llms.txt and being cited by AI systems. Semrush controlled study: no statistical correlation with AI performance.
- **The real exception: developer docs consumed on demand.** AI coding assistants — Cursor, GitHub Copilot, Claude Code — **do** fetch llms.txt when indexing a documentation or developer-tool site during a user's task. That's why Anthropic, OpenAI, Stripe, Cloudflare, Vercel maintain one; Chrome Lighthouse added an audit for it (May 2026).

**Verdict for okfsmith:** ship it when we have a docs site — it's ~30 minutes of work and is a genuine agent-routing map for the dev audience — but never treat it as a citation lever. Complement, never substitute for, the XML sitemap. Note: the June-2026 **ARD spec's `ai-catalog.json`** is the more meaningful "well-known file" for agent discoverability going forward; consider hosting one alongside llms.txt if/when we ship an MCP server or skill.

---

## 2. The surfaces that actually drive discovery for an open-source Python CLI

### GitHub trending (velocity, not total stars)

GitHub's trending algorithm is proprietary, but observed behavior (2026 playbooks, AFFiNE's 28 appearances in 5 months as case study):

- Ranks by **star velocity within the window** (daily/weekly/monthly), time-decayed — a star gained 1 hour ago outweighs one from 20 hours ago. Total star count is not the signal.
- Rough thresholds: **All Languages daily: ~80–150+ stars in one day; language-specific (Python): ~30–60 stars/day**; weekly: ~300–500 over 7 days.
- Anti-bot filtering: brand-new accounts with zero activity are weighted down or discarded. **Buying stars is detectable and community-destroying** — forbidden.
- Repo-health multipliers: healthy fork:star ratio (~1:5 to 1:15), active commits in the past 48h, open/closed issue activity, language/topics set.

Tactical takeaways: **concentrate every launch into a 24–48h window** (velocity matters); Show HN Tuesday–Thursday 7–9am PT with a strong title ("Show HN: [surprising claim] (Python)"); HN → Reddit (r/Python, r/programming) → dev.to deep-dive → X thread — each wave with a *different* content angle; a tasteful star CTA in CLI output is acceptable to some maintainers; weekly release cadence gives weekly reasons to reappear in feeds.

### PyPI search

PyPI (Warehouse) search is text relevance over project name + summary + description (BM25-family). Practical facts:

- **The package NAME is the dominant signal.** Known longstanding quirk (Warehouse issues #10718 / #13597 / #15264): even exact matches don't always rank first (e.g. "tensorflow1" above "tensorflow"), so name choice + summary keywords matter; there is no downloads-weighted popularity ranking to game.
- Levers in our control: one-line summary with natural keywords ("converts messy documents into Google OKF v0.2 knowledge bundles"), `keywords` in pyproject.toml, precise trove classifiers, rendered README as long description, verified project links (Homepage, Repository, Documentation), regular releases (index freshness).
- Note the sibling file `pypi-seo.md` for the deep PyPI playbook; the summary above is the AI-discovery-relevant part.

### Awesome lists (the community-curated discovery layer)

The `awesome-*` pattern is the dominant community-curated discovery layer (10,000+ repos tagged `awesome` on GitHub). Curators explicitly say: **curation, not collection** (sindresorhus/awesome manifesto). PR review criteria across lists: quality, real maintenance activity, clear scope fit, **neutrality (no self-promotion bias)**, stable recent updates. Meta-radars like awesome-curated use cross-source consensus (≥2 independent sources) as the noise filter.

Tactical takeaways: target a small number of on-topic lists with a clean, genuinely-fitting PR (awesome-python's CLI section, awesome-cli-apps, doc-processing/AI-tool lists when the category fits); the PR description must prove maintenance + utility, not hype; being in 2+ independent lists creates the consensus signal that meta-radars and AI assistants both use for *discovery-stage* shortlisting (discovery ≠ evaluation — curators enumerate, they don't rank).

### Launch playbooks: what worked for uv, ruff, aider (and ripgrep, esbuild)

From 2026 analyses of OSS growth (growing-oss-adoption principles; open-source package best-practices research):

1. **Reproducible, named-competitor benchmarks.** ripgrep's enumerated-competitor benchmarks, uv's warm-vs-cold-cache disclosure, esbuild's charts. Credibility comes from the *reproducibility + honesty* package, not the number. **A rigged benchmark is a reputational liability** (Turbopack's numbers were publicly dismantled; Bun's synthetic "fastest" was exposed). For okfsmith: a real, re-runnable benchmark (conversion throughput/quality vs pandoc, MarkItDown, unstructured, Docling on a public corpus) is our single strongest launch asset — but only if the methodology is published alongside the numbers.
2. **Honesty as a credibility weapon.** ripgrep's "curated and biased" + anti-pitch, ruff's "proof-of-concept" framing, SQLite's "Appropriate Uses". Disclosing limitations *alongside* a demonstrated win neutralizes critics and converts scrutiny into trust.
3. **Explain the mechanism so skeptics can self-verify.** ripgrep's finite-automata/SIMD, esbuild's Go+parallelism. Wins the launch-thread argument.
4. **Fundamentals beat scale.** A focused CLI can look professional at 3K stars (dbcli/litecli case): CI, badges, clear README, CHANGELOG (Keep a Changelog), SECURITY.md, dependabot, topics, description, trusted-publisher PyPI releases, terminal GIF/asciinema demo, structured README.
5. **Help text as SEO.** Developers discover CLIs via `--help`/man pages; keywords naturally in help text; tldr pages (community-contributed quick refs); "Built with" badges (the Ruff badge pattern) once adopted.

### AI assistants' direct recommendation path (training data + live search + registries)

What gets a tool *named* by an assistant, in order of evidence:

1. **Being discussed across the sources the model trains on and retrieves from**: README, docs, benchmarks, HN threads, Reddit, Stack Overflow answers, comparison pages, awesome lists. Consistent naming everywhere ("okfsmith — converts messy documents into Google OKF v0.2 knowledge bundles") matters because assistants retrieve by phrasing.
2. **A docs site that is reachable, quotable, and fresh** (llms.txt + llms-full.txt; clean HTML; recency — ChatGPT's 30-day recency preference).
3. **Registries**: MCP Registry + ARD `ai-catalog.json` once we ship an MCP server or Skill; GitHub Agent Finder will query these.
4. **The "comparison query" win**: "best tool to convert documents into knowledge bundles for RAG" — engines lean on existing authoritative comparisons; owning one legitimate comparison page is disproportionately valuable.

---

## 3. Ranked legitimate levers for okfsmith

| # | Lever | Expected impact | Effort | Evidence / notes |
|---|-------|----------------|--------|------------------|
| 1 | **Reproducible benchmark vs named competitors** (pandoc, MarkItDown, unstructured, Docling on a public corpus; publish methodology) | HIGH | Med | ripgrep/uv/esbuild playbook; honesty required — rigged numbers get dismantled |
| 2 | **Real docs site** (GitHub Pages or similar) with clean SEO: `<title>`, meta descriptions, FAQ schema, fresh updates, `llms.txt` + `llms-full.txt` | HIGH | Med | 38% of AI citations from top-10 pages and decoupling; FAQ schema 41% vs 15%; ChatGPT 30-day recency; llms.txt real for coding-agent docs consumption |
| 3 | **README as a GEO asset**: answer-first structure, covers the query fan-out (conversion, OKF v0.2, RAG preprocessing), one clear tagline repeated consistently everywhere, statistics with sources, FAQ section | HIGH | Low | GEO paper + playbooks; consistent naming is what assistants retrieve by |
| 4 | **Launch choreography into a 24–48h velocity window**: Show HN (Tue–Thu 7–9am PT) → Reddit r/Python → dev.to deep-dive → X thread, each with a different angle; aim at Python-daily-trending band (~30–60 stars/day) | HIGH | Med | Velocity, not totals; AFFiNE case; organic only |
| 5 | **One legitimate comparison page**: okfsmith vs pandoc / MarkItDown / unstructured / Docling — genuinely researched, cites sources | HIGH | Med | Comparison queries are where AI engines lean hardest on external sources |
| 6 | **GitHub repo metadata fundamentals**: name, one-line description, topics, homepage URL, social preview, issues/discussions open | MED | Low | GitHub-native discovery tier; health multipliers for trending |
| 7 | **PyPI listing quality**: keyword-rich one-line summary, `keywords`, classifiers, rendered README, verified links, trusted-publisher releases | MED | Low | Name/summary = dominant PyPI ranking signals; see `pypi-seo.md` |
| 8 | **Awesome-list PRs** (2–4 on-topic lists; honest, well-formatted, proving maintenance) | MED | Low | Consensus signal across lists; discovery-stage shortlisting |
| 9 | **Host `ai-catalog.json` (ARD spec)** when an MCP server or Skill ships; register with MCP Registry / GitHub Agent Finder | MED (rising) | Low–Med | June 2026 ARD announcement; this is the emerging agent-discovery layer |
| 10 | **Ship an agent Skill (SKILL.md)** for okfsmith + community `tldr` page | MED | Low–Med | Skills are the agent-facing packaging trend of 2026; tldr is CLI developer discoverability |
| 11 | **Community presence where engines retrieve**: answer Stack Overflow questions in the niche, Reddit threads, "State of document conversion" survey asset (highest-ROI link magnet for dev tools), PostHog-style transparency blogging | MED (long-term) | High | Training-data + live-search recall; brand search volume correlates with citations |
| 12 | **CI/badge/quality fundamentals**: badges, CHANGELOG, SECURITY.md, dependabot, asciinema demo GIF, entry-point docs | LOW–MED | Low | Trust signals for both humans and curators |
| 13 | **CLI `--help` text with natural keywords + docs URL** | LOW | Low | Help text as SEO for developer discovery |

**Notes:** "High" here means *highest expected return among legitimate options for a new CLI* — absolute magnitudes remain probabilistic. Impact on *training-data recall* takes months and cannot be bought; impact on *live-search citation* and *registry discovery* is faster.

---

## 4. What NOT to do (forbidden + wasteful)

1. **No fake stars, no star-buying services.** Detectable (new-account weighting in trending algorithms), community-destroying, and reputationally fatal in the Python/OSS community. Also no fake downloads, no fake reviews.
2. **No keyword stuffing** — in README, PyPI description, docs, or `llms.txt`. Dilutes the extractable claims that actually get cited; reads as spam to curators and assistants alike.
3. **No rigged or synthetic benchmarks.** Turbopack's numbers were publicly dismantled; Bun's "fastest" claim was exposed. Publish methodology or don't publish numbers. The honest-constraint rule also applies: no fake client names, metrics, or testimonials as placeholder "proof".
4. **No pay-to-rank or pay-to-list.** Directories where visibility is purchasable are marked as such by honest players; paying for placement erodes the trust that drives recommendations.
5. **No treating llms.txt as a ranking lever.** Ship it cheap for docs-agent routing; don't spend real effort or money on it as an "AI visibility strategy" — no evidence it changes AI answers.
6. **No duplicating template/boilerplate content** across docs pages (dev-tool sites have been measured stuck at position ~50–68 with identical template prose).
7. **No "growth hacks" that poison AI training data** (astroturfing Reddit, fake comparison blog spam). Assistants increasingly cross-check; poisoned signals backfire.
8. **No claiming guarantees** — on GitHub trending, PyPI placement, or AI citation (see §5).

---

## 5. Realistic expectations (the honest statement)

**What we cannot control or guarantee:**

- **GitHub Trending is not winnable by effort alone.** It ranks star *velocity* within a window against every other repo launching that day; the threshold (roughly 30–60 stars/day for Python-daily) depends on competition we can't predict. We can only *create the conditions*: a real launch window, real distribution, real quality. Nobody can guarantee a trending appearance.
- **PyPI search placement is probabilistic.** PyPI has no popularity-weighted ranking to climb; even exact-name matches don't reliably rank first (known Warehouse behavior). The levers are name, summary, and keywords — necessary, not decisive.
- **AI citation is probabilistic, not purchasable.** Engines cite 3–8 sources per answer; being included depends on crawlability, freshness, query-fan-out coverage, and trust signals we can influence — plus training-data lottery we can't.
- **Training-data recall lags by months.** Work done today enters future model snapshots slowly; there is no legitimate shortcut.

**What IS in our control (and what this report optimizes):** metadata quality, docs quality and freshness, a real benchmark, consistent naming, llms.txt + ai-catalog.json, awesome-list inclusion, launch timing, community participation, and never poisoning our own reputation with shortcuts.

**Measurement:** track (1) AI citation share — monthly manual checks asking ChatGPT/Claude/Gemini/Perplexity "best tool to convert messy documents into knowledge bundles / OKF"; (2) PyPI search position for core keywords; (3) GitHub traffic/referrers; (4) llms.txt fetch logs (expect ~zero from big crawlers — that's normal); (5) star velocity on launch days.

---

## 6. Sources

- GEO paper: Aggarwal et al., KDD 2024 — https://arxiv.org/abs/2311.09735
- GEO playbook (query fan-out, evidence-ranked tactics): https://github.com/xolarvill/seo-workbench/blob/HEAD/skills/write-content/references/geo-optimization.md
- Ahrefs data (citation decoupling 38% vs 76%; <1,000-word pages): https://github.com/xolarvill/seo-workbench/blob/HEAD/skills/write-content/references/geo-optimization.md (cites ahrefs.com/blog)
- 2026 GEO approaches guide (community-driven GEO fastest for B2B; hybrid wins): https://www.aileads.now/blog/generative-engine-optimization-which-approach-wins-in-2026
- llms.txt honest 2026 read (Ahrefs 97%-zero-requests; no major provider consumption): https://agent.mue.app/downloads/does-your-site-need-an-llms-txt.pdf
- llms.txt adoption vs consumption (Originality.ai 8.8×; GPTBot/ClaudeBot/PerplexityBot skip): https://github.com/commoninstruments/agentsurface/blob/HEAD/src/content/docs/discovery/llms-txt.mdx
- llms.txt ranking-effect null results (SE Ranking; Semrush; Google May 2026 guidance): https://rankry.ai/blog/llms-txt-what-it-is-how-to-add/
- llms.txt do-they-work writeup: https://github.com/f9xr/articles/blob/HEAD/_posts/2026-09-08-llms-txt-ai-txt-do-they-work-2026.md
- ARD / ai-catalog.json / GitHub Agent Finder (Jun 17 2026): https://webdeveloper.com/news/agentic-resource-discovery-ard-github-agent-finder/
- GitHub MCP Registry (Jan 2026): https://medium.com/@mvpkenlin/meet-the-github-mcp-registry-a-new-era-of-discoverability-for-ai-powered-developer-tools-eda5a374e804
- GitHub trending mechanics (velocity thresholds; AFFiNE case): https://github.com/gingiris-1031/growth-tools/blob/HEAD/_posts/2026-04-06-how-to-get-on-github-trending.md
- Launch choreography / trending formula (stars come in bursts; never buy): https://github.com/sergey-bar/mjolnir/blob/HEAD/docs/tiers/tier-6-github-stars-playbook.md
- PyPI exact-match ranking quirks (Warehouse #10718/#13597/#15264): https://github.com/pypi/warehouse/issues/15264
- Awesome curation standards (manifesto): https://github.com/sindresorhus/awesome/blob/HEAD/awesome.md
- Awesome consensus signal (cross-source threshold): https://github.com/juantorchia/awesome-curated/blob/HEAD/METHODOLOGY.md
- OSS growth principles (benchmark honesty; ripgrep/uv/Bun/Turbopack): https://github.com/fuyutarow/dotfiles/blob/HEAD/agents/skills/growing-oss-adoption/references/principles.md
- Open-source package best practices (litecli/ruff cases; badges; tldr; trusted publishers): https://github.com/sergeiwallace/ai-cli-utils/blob/HEAD/docs/research/open-source-package-best-practices.md
- Repo discoverability playbook (two-tier GitHub/web metadata): https://github.com/paldom/databricks-apps-fastapi-starter/blob/HEAD/.agents/skills/repo-discoverability/references/discoverability-playbook.md
- Dev-tool SEO playbook (state-of-survey link magnet; vs pages; PostHog model; awesome lists): https://github.com/yashrao2607/fileviewer.dev/blob/HEAD/pi-research-latest-seo-best-practices-2025-for-developer-tools-k0.md
- CLI help-text as SEO / tldr / awesome lists: https://github.com/itsdevcoffee/mojovoice/blob/HEAD/docs/research/2026-02-04-niche-seo-strategies-developer-tools.md

---

*End of report. READ-ONLY task observed — no commits, no pushes, no other files modified.*
