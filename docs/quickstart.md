# Quickstart

Five minutes from zero to a validated, visualized knowledge bundle.

```bash
# 1. Scaffold a bundle
okfsmith init ./kb

# 2. Ingest documents (no LLM needed for the first pass)
okfsmith ingest ./kb notes/ report.pdf --no-llm

# 3. Check OKF v0.2 conformance
okfsmith validate ./kb

# 4. Look at what you built
okfsmith list ./kb
okfsmith graph ./kb --format html   # writes ./kb/viz.html — open it in a browser
```

## What just happened

- `init` created `kb/` with reserved `index.md` (bundle manifest) and
  `log.md` (append-only activity log).
- `ingest` parsed each source, split it into sections, and wrote one
  **draft** concept per section as `kb/<source>/<slug>.md`. Every file is
  SHA-256 fingerprinted, so re-ingesting the same source is a no-op.
- `validate` checked every concept against the OKF §11 conformance rules
  (frontmatter shape, required fields, links, provenance).
- `graph --format html` wrote a self-contained interactive graph
  (`viz.html`, no network needed) — nodes colored by type, shaped by trust
  tier.

## Next steps

- Ingest with an LLM for richer extraction: `okfsmith ingest ./kb paper.pdf`
  (needs Ollama running, or `OPENAI_API_KEY` — see [LLM & no-LLM](llm.md)).
- Mark drafts as reviewed: concepts whose frontmatter gains a `verified`
  entry from a `human:` reviewer show up with the reviewed shape in the
  graph (trust is derived from `verified`, never a literal `trust:` field).
- Serve the bundle to an agent: `okfsmith mcp ./kb` — see [MCP](mcp.md).
