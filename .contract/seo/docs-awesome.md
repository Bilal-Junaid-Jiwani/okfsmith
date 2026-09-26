# okfsmith — Docs SEO Plan + Awesome-List Placement Strategy

**Author:** SEO Specialist 5 (docs SEO + awesome lists) · **Date:** 2026-09-26 · **Status:** read-only plan, no commits
**Scope:** (1) docs structure that ranks, (2) 12 verified awesome lists with contribution rules + draft PR lines + outreach order.
**Honest baseline:** okfsmith is pre-release (GitHub repo not yet public, no PyPI release). Nothing here guarantees rankings or list acceptance. Awesome-list links in GitHub READMEs carry `rel="nofollow"`, so their value is **referral traffic and discovery**, not PageRank. Docs SEO is a 3–6 month compounding play; the near-term wins are (a) the README ranking on GitHub itself, and (b) placements in niche lists where practitioners already browse.

---

## PART 1 — Docs SEO plan

### 1.1 Current state (2026-09-26)

- `README.md` — rich, keyword-dense, already ranks-able once the repo is public (GitHub indexes READMEs well).
- `docs/OVERVIEW.md` — architecture doc; H1 is "okfsmith — Architecture Overview" (not search-friendly; nobody searches "architecture overview").
- No `docs/index.md` hub, no `llms.txt`, no sitemap, no dedicated pages per topic.

### 1.2 Keyword strategy (targets, not promises)

Primary (niche, winnable):
- `OKF v0.2` / `open knowledge format` / `open knowledge format v0.2` ← teammate target
- `okf cli python` ← teammate target
- `okf validator` / `OKF §11`
- `pdf to okf` ← teammate target
- `pdf to knowledge graph` / `document to knowledge graph cli`

Secondary (broader, competitive):
- `rag ingestion cli` ← teammate target
- `llm-ready markdown` ← teammate target
- `knowledge base for ai agents` ← teammate target
- `local RAG knowledge base` / `MCP knowledge base server`
- `python pdf extraction cli` / `notion export to markdown`

Long-tail (FAQ/glossary capture):
- `what is open knowledge format`, `okf vs graphrag`, `does okfsmith need api keys`, `okfsmith vs okf-cli`

Note: "OKF" is an unusually low-competition token right now (the spec is new, mid-2026). Owning `OKF v0.2` + `okf cli python` + `pdf to okf` + `okf validator` early is the realistic win. We do **not** target generic terms like "RAG" or "knowledge management" head-on.

### 1.3 Proposed docs structure (14 pages)

File naming: kebab-case, one H1 per page, H1 carries the keyword. Cross-link map in §1.6.

| # | File | H1 (search-friendly) | Keyword intent |
|---|---|---|---|
| 1 | `docs/index.md` | okfsmith: turn messy documents into OKF v0.2 knowledge bundles | Hub; ranks for "okfsmith" + "OKF v0.2" |
| 2 | `docs/getting-started.md` | Getting started with okfsmith: install, init, ingest in 5 minutes | "okfsmith install", "okf cli python" |
| 3 | `docs/cli-reference.md` | okfsmith CLI reference: init, ingest, validate, list, read, graph, mcp | "okfsmith commands", per-command long-tail |
| 4 | `docs/pipeline.md` (rename/retitle of OVERVIEW.md) | How okfsmith works: the 8-stage pipeline from documents to OKF bundles | "okfsmith pipeline", "document to OKF" |
| 5 | `docs/parsing.md` | PDF and document parsing tiers: free local parsing, Docling, cloud OCR | "pdf to okf", "local pdf extraction no api key" |
| 6 | `docs/extraction.md` | Two-pass LLM concept extraction with provenance and trust tiers | "llm-ready markdown", "provenance knowledge graph" |
| 7 | `docs/validation.md` | OKF §11 validation: hard conformance rules and advisory lints | "OKF §11", "okf validator" |
| 8 | `docs/mcp-server.md` | Serve your OKF bundle over MCP: search, get, list, neighbors, index | "knowledge base for ai agents", "okf mcp" |
| 9 | `docs/skill-pack.md` | SKILL.md pack: teach your agent to read an OKF bundle | "agent skills knowledge base" |
| 10 | `docs/visualization.md` | Browse your knowledge graph: okfsmith graph and viz.html | "knowledge graph visualization html" |
| 11 | `docs/configuration.md` | okfsmith configuration: Ollama defaults and hosted-model env vars | "okfsmith ollama", "okfsmith env vars" |
| 12 | `docs/comparison.md` | okfsmith vs okf-cli vs Go/Rust OKF tools: which one to use | "okfsmith vs okf-cli", "rag ingestion cli" |
| 13 | `docs/faq.md` | okfsmith FAQ: API keys, pricing, vector DB, roadmap | long-tail question queries |
| 14 | `docs/glossary.md` | OKF v0.2 glossary: bundle, concept, sources, trust tier, lifecycle | "what is open knowledge format", "open knowledge format v0.2" |

Fold `docs/OVERVIEW.md` into `docs/pipeline.md` (keep a shim line pointing readers over) — don't leave two competing pages on the same topic (keyword cannibalization).

### 1.4 Page template rules (apply to every page)

- One H1, ≤ 60 chars, keyword in first 3 words.
- First 100 words: plain-English summary answering the page's question (this is what Google shows as the snippet).
- Every code block copy-paste runnable from a fresh install.
- "Next steps" footer with 2–3 internal links (see §1.6).
- No duplicate content between README and docs: README = pitch + quickstart; docs = depth. Link, don't repeat.

### 1.5 llms.txt (repo root + docs site root) — ship cheap, ~30 min

Per the llms.txt convention (llmstxt.org): `#` title, `>` summary blockquote, `##` sections with one-line link descriptions. Draft:

```markdown
# okfsmith

> okfsmith is an Apache-2.0 Python CLI that converts messy documents (PDFs, markdown,
> wiki dumps, Notion exports) into Google's Open Knowledge Format (OKF) v0.2 knowledge
> bundles: markdown files with YAML frontmatter, an index.md, and a log.md. Pipeline:
> ingest → parse → section → extract → link → emit → validate → serve. Free local
> parsing (LiteParse, MarkItDown) and local Ollama by default — no API keys required.
> Ships a built-in OKF §11 validator, a one-command MCP server (search/get/list/neighbors/index),
> a SKILL.md agent pack, and a viz.html graph browser.

## Docs

- [Documentation home](docs/index.md): all guides, one page per topic
- [Getting started](docs/getting-started.md): install, init, ingest in 5 minutes
- [CLI reference](docs/cli-reference.md): init, ingest, validate, list, read, graph, mcp
- [Pipeline](docs/pipeline.md): the 8 stages from raw documents to validated bundle
- [Parsing tiers](docs/parsing.md): Tier 1 local/keyless, Tier 2 Docling, Tier 3 cloud OCR
- [Extraction](docs/extraction.md): 2-pass LLM drafting + critic, provenance, trust tiers
- [Validation](docs/validation.md): OKF §11 hard rules (errors) and advisory lints (warnings)
- [MCP server](docs/mcp-server.md): serve a bundle to agents over stdio
- [SKILL.md pack](docs/skill-pack.md): agent instructions shipped with the bundle
- [Visualization](docs/visualization.md): okfsmith graph → viz.html concept-graph browser
- [Configuration](docs/configuration.md): OKFSMITH_MODEL, ANTHROPIC_API_KEY, OPENAI_API_KEY
- [Comparison](docs/comparison.md): okfsmith vs okf-cli vs Go/Rust OKF tools
- [FAQ](docs/faq.md): API keys, costs, no vector DB, roadmap
- [Glossary](docs/glossary.md): OKF v0.2 terms — bundle, concept, sources[], trust tiers

## Key facts for AI assistants

- Only `type` is required in OKF v0.2 frontmatter; okfsmith also emits `sources[]`,
  `generated`/`verified`, `status`/`stale_after`.
- Validation: §11's three hard rules are errors; broken links are warnings per spec §6.
- No vector database by design; search is lexical + graph traversal; bundles are plain files.
- API keys come from environment variables only, never files or flags.
- License: Apache-2.0. Repo: https://github.com/Bilal-Junaid-Jiwani/okfsmith
```

Honest framing (per teammate's 2026 research: Ahrefs, May 2026 — 97% of llms.txt files got zero requests): this is a **~30-minute ship for docs-agent routing, not a traffic play**. It controls how AI search engines describe okfsmith when they do fetch it; spend nothing more. Keep it under ~100 lines. Regenerate when docs change (CI check: every `docs/` page linked in llms.txt must exist).

### 1.6 Sitemap approach (if docs go to GitHub Pages)

Recommendation: **MkDocs + Material**, `docs/` as source, deploy via `gh-pages` branch (`mkdocs gh-deploy`).

- `mkdocs.yml`: set `site_url: https://bilal-junaid-jiwani.github.io/okfsmith/` — MkDocs auto-generates `sitemap.xml` on build (built-in; no extra plugin needed).
- Material theme gives meta descriptions per page, Open Graph tags, mobile-friendly output — all ranking factors.
- Add `robots.txt` at site root allowing all; add Google Search Console + Bing Webmaster verification meta tags in `mkdocs.yml` `extra`.
- If we do NOT publish a docs site: rely on GitHub's own crawlability (repo tree + README rank fine) and skip the sitemap. Do not half-do it — a hand-written `sitemap.xml` is a maintenance liability.

### 1.7 Internal linking map (hub-and-spoke)

- `docs/index.md` links to all 13 content pages (one-line descriptions = also the llms.txt source of truth).
- Every page links back to `index.md` ("← Docs home") and has a "Next steps" footer.
- Required cross-links: `pipeline.md` ↔ `cli-reference.md` (each CLI command anchors to its stage); `extraction.md` ↔ `validation.md` ↔ `mcp-server.md`; `comparison.md` → `getting-started.md`; `faq.md` → canonical page per answer (never answer fully in the FAQ — link out, avoids duplicate-content dilution).
- README ↔ docs: README links to `docs/index.md` ("Full documentation"); each docs page links to repo root. One direction of truth per fact.

### 1.8 Realistic expectations (read before promising anything)

1. **No #1 guarantees, ever.** "OKF v0.2" and "okf cli python" are winnable because the token is new; "RAG tools" is not winnable against LangChain-era incumbents.
2. **GitHub README is the highest-ROI surface** for the next 90 days — it already exists and is keyword-rich. Docs-site SEO pays off after release + backlinks.
3. **Awesome-list links are nofollow** on GitHub: expect discovery/referral traffic (practitioners browse these lists when choosing tools), not link equity.
4. **Timeline:** docs site indexed in weeks; meaningful organic traffic in 3–6 months, contingent on PyPI release, real usage, and 3–5 accepted list placements.
5. **AI-search surface:** llms.txt + clean docs structure improves how Perplexity/ChatGPT/Claude describe okfsmith — increasingly the discovery path for CLI tools.

---

## PART 2 — Awesome-list placements

Method: 12 candidate lists verified live via web search on 2026-09-26 (repo exists, not archived, recently updated — "last updated" from search-index data). Contribution rules checked against each list's README/CONTRIBUTING where visible. **Never submit before the repo is public + first PyPI release** — dead links get rejected and burn goodwill.

### 2.1 The 12 verified targets

| # | List | URL | Section we'd target | Why we genuinely fit | Contribution rule (verified) | Draft PR line / submission text | Priority |
|---|---|---|---|---|---|---|---|
| 1 | Awesome LLM Knowledge Bases (stevencasey) | https://github.com/stevencasey/awesome-llm-knowledge-bases | Data Ingestion | Near-perfect fit: list is literally "tools for converting web pages, PDFs, papers into clean markdown" + wiki compilation/linting workflow. Has CONTRIBUTING.md at root. | PR following CONTRIBUTING.md; one-line link format | `- [okfsmith](https://github.com/Bilal-Junaid-Jiwani/okfsmith) - Python CLI that forges messy PDFs, wiki dumps, and Notion exports into Google's OKF v0.2 knowledge bundles — with provenance, trust tiers, §11 validation, and a one-command MCP server.` | **P1** |
| 2 | Awesome MCP Servers (tensorblock) | https://github.com/tensorblock/awesome-mcp-servers | docs/knowledge-management--memory.md (Knowledge Management & Memory) | Direct fit: curated KM&MCP servers; BookMCP precedent proves "CLI ingestion + read-only MCP" entries are accepted. Updated 8 days ago. | PR to the section file, matching existing entry format | `okfsmith — Python CLI: messy docs → OKF v0.2 bundles → served over MCP (search/get/list/neighbors/index). Install: pip install okfsmith; run uvx okfsmith mcp --bundle ./kb. Transport: stdio; no auth. Apache-2.0.` | **P1** |
| 3 | Awesome-RAG (Danielskry) | https://github.com/Danielskry/Awesome-RAG | 🧰 Frameworks that Facilitate RAG | 1380 stars, updated 10 days ago. Kreuzberg precedent: "document intelligence library … for RAG ingestion pipelines" is accepted here — ingestion tooling is explicitly in scope. | PR; "Contributing" section in README; match `- [Name](url): Description` format | `- [okfsmith](https://github.com/Bilal-Junaid-Jiwani/okfsmith): Ingestion-first Python CLI for RAG — converts messy documents into Google OKF v0.2 knowledge bundles with provenance, trust tiers, and §11 validation; serves agents via a one-command MCP server.` | **P1** |
| 4 | Awesome Second Brain (mindola-ai) | https://github.com/mindola-ai/awesome-second-brain | Tools section | Updated 7 days ago; neutral, curated second-brain/PKM tool list with `oss`/`local`/`free` tags. okfsmith builds LLM-readable second brains from messy sources — honest fit under "tools for building a second brain." | PR matching tagged format | `- [okfsmith](https://github.com/Bilal-Junaid-Jiwani/okfsmith) - Forge PDFs, wikis, and Notion exports into Google OKF v0.2 knowledge bundles for your second brain: provenance, trust tiers, MCP serving. ([source](https://github.com/Bilal-Junaid-Jiwani/okfsmith)) \`oss\` \`cli\` \`local\` \`free\`.` | **P1** |
| 5 | Awesome MCP Servers (wong2) | https://github.com/wong2/awesome-mcp-servers | n/a — directory submission | 4324 stars, flagship MCP list — highest visibility of any target. **But: NO PRs accepted** (README states: "We do not accept PRs. Please submit your MCP on the website"). | Submit at https://mcpservers.org/submit — do not open a PR | Submission text: `okfsmith — one-command MCP server serving OKF v0.2 knowledge bundles to AI agents over stdio: search, get, list, neighbors, index. Every concept carries provenance (sources[]), trust tiers, and lifecycle metadata. Apache-2.0. Python.` | **P2** (high reach, different route) |
| 6 | Awesome Context AI (louis030195) | https://github.com/louis030195/awesome-context-ai | Personal Knowledge Management | Has an explicit PKM table (Obsidian, Logseq, Khoj, AnythingLLM…). okfsmith is the document→KB ingestion half of that workflow — complementary, not duplicative. | PR matching `| Tool | Description | Stars |` table format | `\| [okfsmith](https://github.com/Bilal-Junaid-Jiwani/okfsmith) \| Python CLI that converts messy documents into Google OKF v0.2 knowledge bundles (provenance, trust tiers, §11 validation) and serves them to AI agents over MCP \|` | **P2** |
| 7 | Awesome Knowledge Management (bart6114) | https://github.com/bart6114/awesome-knowledge-management | Platforms, Applications and Tools | Updated 28 days ago; KM-focused list already links a PDF knowledge tool (Polar). okfsmith is a KM tool for the LLM era — same shelf. | PR in list format `- [Name](url) - Description` | `- [okfsmith](https://github.com/Bilal-Junaid-Jiwani/okfsmith) - Python CLI forging messy documents (PDFs, wiki dumps, Notion exports) into Google's OKF v0.2 knowledge bundles with provenance, trust tiers, built-in validation, and MCP serving.` | **P2** |
| 8 | Awesome LLM Tools (awdemos) | https://github.com/awdemos/awesome-llm-tools | 6. RAG Pipelines | Updated 71 days ago; RAG-pipelines and agent-memory tables. okfsmith is document-ingestion RAG tooling (not another framework) — fits the "Document-heavy RAG" column honestly. | PR matching `| Tool | Description | Best For |` table format | `\| [okfsmith](https://github.com/Bilal-Junaid-Jiwani/okfsmith) \| Ingestion-first RAG tooling: messy docs → Google OKF v0.2 bundles (provenance, trust tiers, §11 validation) + one-command MCP retrieval server \| Document-ingestion RAG \|` | **P3** |
| 9 | awesome-llm (uhub) | https://github.com/uhub/awesome-llm | RAG / knowledge sections | Updated 6 days ago; large general LLM list (Graphiti, UltraRAG, OpenKB accepted — shows KB/memory tooling is in scope). Lower precision fit = lower priority. | PR matching list format | `- [okfsmith](https://github.com/Bilal-Junaid-Jiwani/okfsmith) - Python CLI converting messy documents into Google OKF v0.2 knowledge bundles (provenance, trust tiers, §11 validation) with one-command MCP serving for agents.` | **P3** |
| 10 | awesome-mcp (vladimirrott) | https://github.com/vladimirrott/awesome-mcp | MCP servers section | Updated 64 days ago; auto-updated daily; Python MCP servers cataloged. Smaller fit signal, but entry is cheap. | PR in `- [org/repo](url) — Description ☆`star` format | `- [Bilal-Junaid-Jiwani/okfsmith](https://github.com/Bilal-Junaid-Jiwani/okfsmith) — One-command MCP server for Google OKF v0.2 knowledge bundles: search/get/list/neighbors/index with provenance on every concept` | **P3** |
| 11 | awesome-mcp-1 (angadsingi1) | https://github.com/angadsingi1/awesome-mcp-1 | MCP tools/servers | Updated 64 days ago; Python MCP servers accepted (chroma-mcp, postgres-mcp precedents). Curated but smaller reach. | PR matching list format | `- [okfsmith](https://github.com/Bilal-Junaid-Jiwani/okfsmith) - Python CLI + one-command MCP server for Google OKF v0.2 knowledge bundles built from messy documents; lexical+graph search, provenance on every concept.` | **P4** |
| 12 | awesome-mcp-servers (bensynapse/habitoai) | https://github.com/bensynapse/awesome-mcp-servers-habitoai | MCP servers list | Updated 33 days ago; another curated MCP catalog. Redundant reach vs #2/#5, but legitimate and cheap. | PR matching list format | `- [okfsmith](https://github.com/Bilal-Junaid-Jiwani/okfsmith) - Forge messy documents into Google OKF v0.2 knowledge bundles and serve them to agents over MCP (search, get, list, neighbors, index). Apache-2.0.` | **P4** |

Notes:
- stevencasey/awesome-llm-knowledge-bases is a **fork with 0 stars** (created Jul 2026) — included anyway because its "Data Ingestion" section is the single best topical fit of any list found; quality of fit beats raw reach for P1.
- blueskyid666/awesome-mcp-2 was checked and **rejected**: it's a giant auto-dump (2800+ entries, star-sorted), not a curated list — a placement there signals spam, not quality.
- mayne-x/awesome-cli was checked and **rejected for now**: it claims 1633 tools "auto-discovered and updated daily" — generic CLI scope with unclear addition path; okfsmith would be one line among 1600+. Revisit only if a clear contribution path is confirmed.
- URL rule honored: every URL above was returned verbatim by web search on 2026-09-26; the okfsmith repo URL comes from the project's own README (repo not yet public at plan time).

### 2.2 Outreach sequence

**Preconditions (all must be true before wave 1):** GitHub repo public · first PyPI release tagged · README quickstart verified working · docs/ has index page + llms.txt committed · no placeholder links.

**Wave 1 — best fit, likely fast merge (week 1–2, 2 PRs/week):**
1. stevencasey/awesome-llm-knowledge-bases (Data Ingestion) — follow CONTRIBUTING.md exactly.
2. tensorblock/awesome-mcp-servers (knowledge-management--memory.md) — match entry format, include install + transport + license fields.

**Wave 2 — reach + adjacent fit (week 3–4):**
3. Danielskry/Awesome-RAG (Frameworks that Facilitate RAG) — reference the Kreuzberg ingestion precedent in the PR body so the maintainer sees the fit is established.
4. mindola-ai/awesome-second-brain — tagged-format PR.
5. wong2/awesome-mcp-servers — **not a PR**: submit via mcpservers.org/submit using the draft text above.

**Wave 3 — long tail (week 5+):**
6. louis030195/awesome-context-ai (PKM table)
7. bart6114/awesome-knowledge-management
8. awdemos/awesome-llm-tools (RAG Pipelines table)
9. uhub/awesome-llm
10. vladimirrott/awesome-mcp, angadsingi1/awesome-mcp-1, bensynapse/awesome-mcp-servers-habitoai — batch these three in one session; they are the lowest-cost.

**Rules of engagement (no-spam):**
- One PR per list, from the maintainer's own GitHub account (Bilal-Junaid-Jiwani). Brand-new accounts mass-PRing lists get flagged — pace at 2–3 PRs/week max.
- PR body template: what it is (one line) · why it fits this list's section (one line, cite a sibling entry) · license (Apache-2.0) · proof it works (link to PyPI + a docs page). No hype, no superlatives.
- If a PR is closed/rejected, do not re-PR or argue — move on. Log the outcome in this file.
- Quarterly sweep: re-check each list's activity; drop dead lists (no commits in 6 months) from future waves.

### 2.3 Honest expectations for awesome-list work

- Acceptance is curator-dependent; expect a ~30–50% merge rate on P1–P2 targets, lower on P3–P4.
- GitHub README links are `rel="nofollow"`: value = **referral traffic from practitioners browsing lists**, not SEO link equity.
- Realistic outcome of 5–7 merged placements over 6–8 weeks: steady trickle of discovery traffic (tens of visits/week per list), plus the social proof of being listed next to known tools.
- The single highest-leverage placement is wong2's directory (via mcpservers.org submit) — it's where MCP practitioners actually search, not browse.

---

## Appendix — verification log (2026-09-26)

- List existence + activity verified via web search; "last updated" from search-index metadata (stevencasey 77d, tensorblock 8d, Danielskry 10d, mindola-ai 7d, wong2 74d, louis030195 114d/8d crawl, bart6114 28d, awdemos 71d, uhub 6d, vladimirrott 64d, angadsingi1 64d, bensynapse 33d).
- wong2 contribution rule verified by reading the README directly: "We do not accept PRs. Please submit your MCP on the website: mcpservers.org/submit".
- stevencasey contribution rule verified: CONTRIBUTING.md present at repo root; README has explicit Contributing section.
- Danielskry contribution rule verified: README outline contains a Contributing section; Kreuzberg entry confirms ingestion tooling is accepted under "Frameworks that Facilitate RAG".
- tank lists rejected: blueskyid666/awesome-mcp-2 (un-curated dump), mayne-x/awesome-cli (unclear addition path, 1600+ tools), anchalaprasanth19-sketch/awesome-rag (fork of Danielskry — submit to the original).
- teammate 2026 research cited: Ahrefs May 2026 — 97% of llms.txt files received zero requests → llms.txt ships cheap (~30 min), no further spend.
