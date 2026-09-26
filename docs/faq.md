# FAQ

**What is OKF?**
The Open Knowledge Format (v0.2), Google's spec for portable knowledge
bundles: markdown files with YAML frontmatter plus reserved `index.md` /
`log.md` files. Canonical reference:
`GoogleCloudPlatform/open-knowledge-format` on GitHub.

**What does okfsmith do that a folder of markdown doesn't?**
It enforces the OKF §11 conformance rules (`validate`), tracks provenance
and trust tiers, dedups sources by SHA-256, links concepts into a graph, and
serves the bundle to agents over MCP — while keeping everything as plain
markdown you can read without the tool.

**Do I need an LLM?**
No. `--no-llm` ingests fully offline. An LLM (Ollama or an OpenAI-compatible
API) gives richer extraction; it never changes the bundle format.

**Is my data sent anywhere?**
Not by okfsmith itself. Parsing, validation, and the graph viewer are
offline. Only LLM extraction contacts a model endpoint — Ollama keeps that
on your machine too.

**Which Python versions?**
3.10+.

**What license?**
Apache-2.0.

**Can I use the bundle without okfsmith?**
Yes — it's markdown + YAML. `index.md` lists the concepts; each concept is
one file. Any markdown reader works.

**How is this different from a vector database?**
okfsmith builds a curated, validated, provenance-tracked bundle — not an
embedding index. The two complement each other; the MCP `search` tool does
full-text search over the finished bundle.
