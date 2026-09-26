# PyPI Listing SEO — Specialist 4 Plan (READ-ONLY, no changes applied)

**Package:** `okfsmith` 0.1.0 · Apache-2.0 · CLI · not yet published · PyPI name verified free
**Repo:** https://github.com/Bilal-Junaid-Jiwani/okfsmith

---

## 1. PyPI ranking factors (Warehouse + Elasticsearch, as of 2026)

How PyPI search actually works, from the public Warehouse codebase and community docs.
No factor below is a guess; all are documented behavior of pypi.org search.

1. **Project name dominates.** Elasticsearch boosts `normalized_name` the hardest;
   exact/prefix name matches outrank everything else. `okfsmith` is a unique name,
   so searches for "okfsmith" (or the prefix "okf") will surface it at/near the top
   regardless of other metadata. This is the single strongest, least controllable
   factor — and it's already favorable.
2. **Summary (`description`, the one-liner) is indexed and displayed.** It is
   shown under the name in search results and used as the Google meta-description
   of the project page. Terms in the summary count toward full-text matches.
3. **`keywords` (free-form Metadata Keywords) is indexed and searchable.** It is
   the main lever for discovery queries that don't contain the package name
   (e.g. `knowledge base cli`, `mcp server knowledge`). Keep it honest and
   domain-specific; keyword stuffing of unrelated popular terms is a trust signal
   failure, not a ranking trick.
4. **Long description (README) matters less for ranking, more for the page.**
   The README is the project-page body and what Google indexes off the PyPI page.
   A keyword-rich first paragraph and descriptive H2s help Google, not PyPI's
   internal scorer in any meaningful way. Badges, tables, code blocks render via
   readme_renderer — keep GFM clean so rendering never fails.
5. **Classifiers do NOT affect full-text ranking.** Trove classifiers power the
   sidebar *facet filters* on pypi.org search (Environment, Framework, Topic,
   License, Python version) and signal maturity/audience to humans and tools.
   They do not boost Elasticsearch relevance — set them for accuracy and
   filterability, not ranking games.
6. **`[project.urls]` drives trust and click-through, not ranking.** Warehouse
   recognizes `Homepage`, `Documentation`, `Repository`, `Issues`, `Changelog`
   with sidebar icons; uploads via Trusted Publishing (OIDC) get a green ✓.
   These matter for humans deciding to install, and for Google's repo association.
7. **Downloads, stars, recency do not factor into PyPI's Elasticsearch score.**
   A brand-new package with zero downloads can rank for exact-name queries; for
   competitive generic queries ("markdown", "knowledge"), established packages
   will outrank it regardless of metadata polish. Be honest about this.
8. **Google indexes pypi.org/project pages well.** The page `<title>` is
   `{name} {version} · PyPI` and the snippet comes from the summary. This is
   where a good one-liner pays off beyond pypi.org itself.

**Bottom line for okfsmith:** the package wins exact-name discovery automatically.
The realistic goal of this plan is (a) to be *findable* for targeted multi-term
queries a real user would type (`knowledge base cli`, `pdf knowledge extraction`,
`okf bundle`, `mcp knowledge server`), and (b) to look credible when the page is
opened from Google or pypi.org search results. No #1 guarantees.

---

## 2. Audit of current metadata

| Field | Current | Verdict |
|---|---|---|
| `description` | `"Documents → OKF knowledge bundles"` | ⚠️ Weak. Arrow `→` carries no search terms; "Documents" is generic; missing the high-value terms people search for: **CLI**, **PDF**, **knowledge base**, **MCP**, **LLM extraction**. This text becomes the search-result snippet and Google meta description. |
| `keywords` | `okf, knowledge, markdown, cli, knowledge-graph` | ⚠️ Thin. Missing: `pdf`, `mcp`, `rag`, `llm`, `notion`, `wiki`, `extraction`, `frontmatter`, `knowledge-base`, `ocr`. Generic `knowledge` duplicates `knowledge-graph` intent; no mention of the agentic/MCP angle, the tool's main differentiator. |
| `classifiers` | Dev Status 3-Alpha; Developers; Apache; OS Independent; Python 3/3.10/3.11/3.12; `Topic :: Text Processing :: Markup :: Markdown` | ⚠️ Incomplete. Only one Topic classifier; no `Environment :: Console` (it IS a CLI — the exact facet CLI users filter by); no `Topic :: Utilities`; no Indexing or AI topic for the extraction/agent side. |
| `project.urls` | **Missing entirely** | 🔴 Biggest gap. No Homepage/Repository/Documentation/Issues links on the PyPI sidebar. Every credible package has these. |
| `requires-python` | `>=3.10` + matching version classifiers | ✅ Correct and consistent. |
| `readme = "README.md"` | shorthand, markdown inferred | ✅ Fine. README renders; structure is solid (badges → H1 → bold tagline → quickstart). |
| `license = { text = "Apache-2.0" }` | works | ⚠️ Minor. SPDX expression `license = "Apache-2.0"` is the modern form (PEP 639); needs setuptools ≥77. Current form is valid — low priority. |
| `authors` | `okfsmith-team` | ✅ Acceptable for a team package. |

**README rendering audit (what PyPI will show):**
- ✅ Badges at top render (shields.io, alt text present).
- ✅ First body line is the bold tagline with strong keywords — good for Google.
- ⚠️ Relative links `docs/OVERVIEW.md`, `LICENSE`, `CONTRIBUTING` resolve against
  the PyPI page URL and 404 there. Suggest absolute GitHub URLs for the two most
  important ones (OVERVIEW, LICENSE).
- ✅ H2 headings (`## Why okfsmith`, `## How it compares`, …) are descriptive;
  consider retitling `## Why okfsmith` → `## Why okfsmith — ingestion-first OKF`
  so the H2 carries a search term. Minor.
- ✅ Code blocks, tables are readme_renderer-safe GFM.

---

## 3. Proposed changes (exact diffs for the builder)

### 3a. `pyproject.toml` — the full proposed diff

```diff
 [project]
 name = "okfsmith"
 version = "0.1.0"
-description = "Documents → OKF knowledge bundles"
+description = "CLI that forges PDFs, markdown, and wikis into Open Knowledge Format (OKF) knowledge bundles"
 readme = "README.md"
 requires-python = ">=3.10"
 license = { text = "Apache-2.0" }
 authors = [{ name = "okfsmith-team" }]
-keywords = ["okf", "knowledge", "markdown", "cli", "knowledge-graph"]
+keywords = [
+    "okf",
+    "open-knowledge-format",
+    "knowledge-bundle",
+    "knowledge-base",
+    "knowledge-graph",
+    "pdf",
+    "markdown",
+    "notion",
+    "wiki",
+    "cli",
+    "mcp",
+    "llm",
+    "extraction",
+    "ocr",
+    "frontmatter",
+    "agents",
+    "rag",
+]
 classifiers = [
     "Development Status :: 3 - Alpha",
+    "Environment :: Console",
     "Intended Audience :: Developers",
     "License :: OSI Approved :: Apache Software License",
     "Operating System :: OS Independent",
     "Programming Language :: Python :: 3",
     "Programming Language :: Python :: 3.10",
     "Programming Language :: Python :: 3.11",
     "Programming Language :: Python :: 3.12",
+    "Topic :: Scientific/Engineering :: Artificial Intelligence",
+    "Topic :: Text Processing :: General",
+    "Topic :: Text Processing :: Indexing",
     "Topic :: Text Processing :: Markup :: Markdown",
+    "Topic :: Utilities",
 ]
 dependencies = [
     "typer>=0.12",
     "pyyaml>=6",
     "rich>=13",
 ]
+
+[project.urls]
+"Homepage" = "https://github.com/Bilal-Junaid-Jiwani/okfsmith"
+"Documentation" = "https://github.com/Bilal-Junaid-Jiwani/okfsmith#readme"
+"Repository" = "https://github.com/Bilal-Junaid-Jiwani/okfsmith"
+"Issues" = "https://github.com/Bilal-Junaid-Jiwani/okfsmith/issues"
```

### 3b. Rationale per change

- **`description` (one-liner):** 98 chars, no unicode symbols, front-loads the
  three highest-value discovery nouns: *CLI*, *PDFs/markdown/wikis* (the messy
  inputs — what a user searches for when they have the problem), and *OKF
  knowledge bundles* (the output — the standard's name, for spec-aware users).
  Fits PyPI's search-result truncation and becomes the Google snippet.
- **`keywords`:** each term is a word a real user would type when discovering
  this tool. Deliberately NOT included: `vector-database` (the tool explicitly
  rejects vector search — honest constraint), `attestation`, `chatbot`.
  `rag` is included because knowledge bundles served over MCP are the RAG
  substrate — defensible, not bait. 17 terms, all single-hyphenated or single
  words, comma-joined by setuptools as required.
- **Classifiers:**
  - `Environment :: Console` — the CLI facet users filter by; the most important
    missing classifier.
  - `Development Status :: 3 - Alpha` — kept. Honest for a 0.1.0 pre-first-release
    package. Bump to `4 - Beta` only when the team declares feature-freeze toward
    1.0 (roadmap item), and to `5 - Production/Stable` at 1.0.
  - `Topic :: Utilities` — the canonical home for CLIs.
  - `Topic :: Text Processing :: General` + `:: Indexing` — the tool ingests and
    indexes documents; alongside the existing `Markup :: Markdown` this covers
    the document-processing facets.
  - `Topic :: Scientific/Engineering :: Artificial Intelligence` — the 2-pass LLM
    extraction and agent-facing MCP serving make this accurate, not aspirational.
  - All classifier strings are from the official Trove list (verified against
    pypi.org/classifiers naming conventions).
- **`[project.urls]`:** all four are recognized sidebar labels in Warehouse.
  URLs are the real repo/issue URLs (verified in README). `Documentation` points
  at the README via `#readme` — honest, since no standalone docs site exists yet;
  replace with the real docs URL when one ships. `Changelog` deliberately
  omitted — no CHANGELOG.md exists (checked), and pointing at a nonexistent
  anchor is worse than omitting. Recommendation: add a `CHANGELOG.md` at first
  release and then add `"Changelog" = "https://github.com/Bilal-Junaid-Jiwani/okfsmith/blob/main/CHANGELOG.md"`.
- **Not changed:** `name` (already unique/strong), `requires-python`, version
  classifiers, `license` form (SPDX expression is a nice-to-have requiring
  setuptools ≥77; `{ text = "Apache-2.0" }` is valid today — flag for the
  builder, don't block on it).

### 3c. README headline tweaks for PyPI rendering

Minimal, rendering-safe edits — all links below are the real repo URLs:

1. Make the two links PyPI users will actually click absolute:
   - `See [docs/OVERVIEW.md](docs/OVERVIEW.md)` →
     `[docs/OVERVIEW.md](https://github.com/Bilal-Junaid-Jiwani/okfsmith/blob/main/docs/OVERVIEW.md)`
   - `[LICENSE](https://github.com/Bilal-Junaid-Jiwani/okfsmith/blob/main/LICENSE)`
     is already absolute — keep.
2. Consider retitling `## Why okfsmith` → `## Why okfsmith — ingestion-first OKF`
   so the heading carries a discoverable phrase on the PyPI page. Optional.
3. Everything else (badges, tagline, tables, code fences) is PyPI-safe; no
   changes needed.

---

## 4. Expected impact (honest)

- **Exact-name searches (`okfsmith`, `okf`):** already top-ranked by name weight;
  the metadata changes don't move this — it was never at risk.
- **Targeted multi-term discovery** (`knowledge base cli`, `pdf knowledge
  extraction`, `mcp knowledge server`, `okf bundle`, `notion knowledge cli`):
  meaningfully better recall. Keywords + summary terms are the indexed fields
  that match these queries; before this plan, `mcp`, `pdf`, `rag`, `agents`,
  `extraction` appeared nowhere in the indexed metadata. Realistic outcome:
  appearing *in* the results for these queries, not ranking #1 against
  established packages with years of history.
- **Google / web discovery:** the one-liner becomes the page snippet; project
  URLs enable repo association. This is likely the largest *absolute* traffic
  source for a new package — people Google "okfsmith" or "okf cli python", and
  the PyPI page will rank for the exact name.
- **Trust / click-through:** sidebar links + full classifier set make the page
  look like a maintained project. Humans install what looks maintained.
- **What this will NOT do:** outrank `markitdown`, `langchain`, or other
  established packages on generic single-term queries; move the needle on
  PyPI's internal relevance beyond recall; or substitute for release activity,
  documentation, and real adoption (the factors that actually compound over
  time: recurring releases, external links, usage).
