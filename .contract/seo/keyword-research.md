# okfsmith — Keyword Research (SEO Specialist 2 of 5)

**Date:** 2026-09-26 · **Role:** Keyword research for discoverability
**Scope:** Where a new Apache-2.0 Python CLI ("okfsmith", PyPI free, future GitHub `Bilal-Junaid-Jiwani/okfsmith`) can realistically rank.

**Product in one line:** Converts messy documents (PDFs, Notion exports, wikis, markdown) into Google's OKF v0.2 knowledge bundles (markdown + YAML frontmatter for AI agents / RAG).

## Landscape notes (from web research)

- OKF = Open Knowledge Format, Google Cloud open spec (v0.1 June 2026, v0.2 current): a knowledge bundle is a directory of markdown files with YAML frontmatter (`type` is the only required field), cross-linked, with optional `index.md` / `log.md`. It formalizes the "LLM-wiki" pattern; vendor-neutral; git-versionable.
- Existing tooling found: `okf-cli` (auto-medica-labs, Python, **markdown→OKF only**), Go `okfcli/okf` (validate/lint/index/search, ~24 stars), Rust `abatyuk/okf` (36 commands + MCP + agent skills), Haskell `shinzui/okf`, `chasedputnam/okf-cli` (crawl docs → OKF → serve via MCP), `raimannma/okf-cli` (Rust agent-oriented CLI + MCP server). **None ingest PDFs/Notion exports** — that's okfsmith's gap and keyword wedge.
- Adjacent spaces with high search volume but higher competition: PDF→markdown for RAG (MarkItDown, Docling dominate), llms.txt generators (llmstxt-gen, etc.), MCP servers.
- Discovery reality check: a brand-new PyPI package + GitHub repo will NOT rank on Google for generic terms like "convert pdf to markdown" (Microsoft MarkItDown, IBM Docling, LangChain own that). The winnable surfaces are: **GitHub search/topics, PyPI search, awesome lists, AI-engineer long-tail queries, and the "OKF" branded space** which is young and low-competition.

---

## Keyword table

| # | Keyword | Intent | Competition | Target surface | Priority |
|---|---------|--------|-------------|----------------|----------|
| 1 | `open knowledge format` | Informational / navigational — devs who heard of OKF want the spec and tooling | **L** (spec repo + a few community guides; almost no tooling pages yet) | GitHub README headers + PyPI long description + docs landing page | **P0** |
| 2 | `okf bundle` / `okf knowledge bundle` | Transactional — user has/needs a bundle, wants to build or validate one | **L** (tiny SERP surface; community repos only) | GitHub repo description (contains "okf"), PyPI keywords, README H1/H2 | **P0** |
| 3 | `okf python` / `okf cli python` | Transactional — Python dev wants an OKF CLI in Python (vs Go/Rust) | **L** (only `auto-medica-labs/okf-cli` occupies this) | GitHub repo description ("Python CLI for OKF"), PyPI keywords: `okf`, `knowledge-format`, topics on GitHub | **P0** |
| 4 | `markdown to okf` | Transactional — closest existing intent; direct rival is `okf-cli` | **L–M** (okf-cli is the only occupant; still beatable with more features) | README comparison section ("okfsmith vs okf-cli"), docs migration page, PyPI keywords | **P0** |
| 5 | `pdf to okf` / `pdf to knowledge bundle` | Transactional — **uncontested niche**; nobody targets this phrase | **L** (no indexed results) | README H2 section, docs page "Convert PDFs to OKF bundles", PyPI keywords | **P0** |
| 6 | `convert notion export to llm-ready markdown` | Transactional long-tail — Notion→LLM pipeline builders | **L** (scattered Notion-to-markdown skills, none LLM/OKF-positioned) | README H2 + dedicated docs page ("Notion exports → OKF bundles"), awesome-list pitches | **P1** |
| 7 | `notion export to markdown cli` | Transactional — high-intent CLI searchers | **M** (notion-to-md npm ecosystem, some Python tools) | PyPI keywords + README "works with Notion markdown exports" + docs recipe page | **P1** |
| 8 | `knowledge base for ai agents` | Informational/transactional — LLM engineers building agent knowledge | **M** (broad; docs for frameworks rank, but CLI-specific results are thin) | GitHub topics (`ai-agents`, `knowledge-base`, `rag`), README intro paragraph | **P1** |
| 9 | `rag ingestion cli` / `rag document ingestion` | Transactional — RAG builders looking for an ingestion step | **M** (LangChain/LlamaIndex tutorials dominate; CLI tooling results thin) | GitHub topics (`rag`, `llm`), PyPI keywords, README section "Use in RAG pipelines" | **P1** |
| 10 | `llm-ready markdown` | Transactional/commercial investigation — emerging phrase for agent-readable docs | **L** (used in marketing copy; almost no tools claim it as a keyword) | README one-liner ("messy docs → LLM-ready markdown"), PyPI long description | **P1** |
| 11 | `markdown + yaml frontmatter knowledge base` | Informational — people discovering the OKF/LLM-wiki pattern | **L** | Docs explainer page ("What is OKF?"), README "Why OKF" section | **P2** |
| 12 | `okf validator` / `validate okf bundle` | Transactional — quality-check intent; Go/Rust validators exist | **M** (Go + Rust tools rank for "validate") | Docs page + README feature list (include a `validate` command!) | **P2** |
| 13 | `mcp server knowledge base` | Transactional — MCP ecosystem builders | **M–H** (crowded MCP server space) | Only via README mention + future `serve --mcp` feature; do NOT lead with this | **P2** |
| 14 | `wiki to markdown` / `confluence export to markdown` | Transactional long-tail | **M** | Docs recipe pages (one per source type: wiki, confluence, mkdocs) | **P2** |
| 15 | `convert pdf to markdown for rag` | Transactional — big volume | **H** (MarkItDown, Docling, Unstructured own it) | Mention in README as input capability only; do not target as primary keyword | **P3** |
| 16 | `llms.txt` | Informational/transactional | **H** in general; **L** for "llms.txt + OKF" | Only as a README comparison paragraph ("OKF vs llms.txt"), not a target | **P3** |
| 17 | `open knowledge format vs llms.txt` | Informational — comparison intent | **L** (one community guide covers it) | Docs FAQ page / README FAQ — cheap to own, captures spec-curious traffic | **P2** |

### Long-tail opportunities (low competition, high intent — own with one docs page each)

- `convert notion export to llm-ready markdown` (P1)
- `pdf to okf bundle python` (P1)
- `turn messy pdfs into agent-readable knowledge base` (P2)
- `notion markdown export cleanup for rag` (P2)
- `mkdocs to knowledge bundle for ai agents` (P2)
- `okf bundle example python` (P2 — docs page with a worked example)
- `how to structure markdown for ai agents` (P2 — guides rank well in this niche)
- `self-hosted knowledge base cli no vector database` (P2 — OKF's "format, not platform" angle)

---

## Recommended title / description / one-liner variants

### GitHub repo (Bilal-Junaid-Jiwani/okfsmith)

**Repo name:** `okfsmith` · **Suggested topics:** `okf` `open-knowledge-format` `knowledge-base` `rag` `llm` `ai-agents` `markdown` `pdf-to-markdown` `notion` `python` `cli` `mcp` (add `mcp` only if/when a serve feature exists)

**Description variants (pick one, ≤ GitHub limit):**
1. *(recommended)* `Forge messy docs into OKF knowledge bundles — Python CLI that converts PDFs, Notion exports, wikis and markdown into Google's Open Knowledge Format for AI agents and RAG.`
2. `Python CLI: messy documents (PDF, Notion, wiki, markdown) → LLM-ready OKF knowledge bundles (Google Open Knowledge Format v0.2).`
3. `Turn PDFs, Notion exports and wikis into agent-readable knowledge bundles — open-source Python CLI for Google's OKF v0.2.`

### PyPI package ("okfsmith")

**Summary (one-liner, shows in `pip search` / PyPI listing):**
- *(recommended)* `Forge PDFs, Notion exports, wikis and markdown into OKF knowledge bundles for AI agents and RAG (Google Open Knowledge Format v0.2).`
- Alt: `CLI that converts messy documents into LLM-ready Open Knowledge Format (OKF) knowledge bundles.`

**PyPI keywords (comma-separated, max impact):**
`okf, open-knowledge-format, knowledge-bundle, knowledge-base, rag, llm, ai-agents, pdf-to-markdown, notion, markdown, yaml-frontmatter, document-conversion, cli`

**PyPI classifiers to set:** `Development Status :: 3 - Alpha`, `Intended Audience :: Developers`, `Topic :: Scientific/Engineering :: Artificial Intelligence`, `Topic :: Text Processing :: Markup :: Markdown`, `Topic :: Utilities`.

### Docs / README header structure (keyword-bearing H1–H3s)

- H1: `okfsmith — forge documents into OKF knowledge bundles`
- H2: `Convert PDFs to OKF bundles` · `Notion exports → LLM-ready markdown` · `Wikis and docs sites → knowledge bundles` · `Validate any OKF bundle` · `okfsmith vs okf-cli` · `OKF vs llms.txt`
- Each H2 gets a dedicated docs page → captures long-tail queries above.

### Awesome-list targets (free, high-trust backlinks in this niche)

- `josezuma/awesome-ai-visibility` (llms.txt Tools & Resources / Open Source Projects sections)
- `dapollonsky/awesome-ai-visibility-1` (same family)
- Any `awesome-rag`, `awesome-llm`, `awesome-mcp` lists with a "tools" section — pitch under "Knowledge / ingestion"
- Community OKF guides/skill repos (e.g. OKF community guide authors) — offer okfsmith as the ingestion tool link

---

## Honest expectations

- **No #1 guarantees, and no fast ones.** Google rankings for even low-competition terms take weeks–months; PyPI/GitHub search respond faster (days) because they're smaller indexes.
- **Where we can realistically win:** GitHub search for `okf python` / `okf cli`, PyPI search for `okf`, long-tail docs pages (`pdf to okf`, `notion export to llm-ready markdown`), and awesome-list placements. The OKF space is ~3 months old (spec June 2026) — early movers get durable positioning.
- **Where we will lose:** generic `pdf to markdown`, `rag ingestion`, `llms.txt` — incumbents (MarkItDown, Docling, LangChain docs) have years of domain authority. Mention these capabilities; don't build the strategy on them.
- **Biggest ranking lever isn't keywords:** it's a genuinely useful README (worked example in <2 min), a `validate` command (matches existing transactional queries), and docs pages per input type. Search engines and humans both reward that.
- **The honest caveat to carry:** OKF is a niche-within-a-niche today. Keyword work buys discoverability *within* the AI-engineer community; mainstream volume only arrives if OKF adoption grows. The strategy above is sized for that reality.
