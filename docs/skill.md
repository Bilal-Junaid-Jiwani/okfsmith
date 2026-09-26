# Skill pack

The `okfsmith-build` skill teaches an AI agent to use okfsmith end-to-end:
scaffold a bundle, ingest sources, validate conformance, and serve over MCP.

- Location in this repo: `skills/okfsmith-build/SKILL.md`
- Install it into your agent's skill directory (e.g. `~/.agents/skills/`)
  or reference it from the repo.

Trigger phrases: *okf, knowledge bundle, convert docs to OKF, ingest PDF to
knowledge base, bundle validator, open knowledge format*.

## Scope (what the skill is for — and not for)

**Use for:** converting PDFs, markdown collections, wiki dumps, or Notion
exports into OKF v0.2 bundles; validating bundles; serving bundles over MCP;
auditing provenance and trust metadata.

**Do not use for:**

- code-graph extraction from repositories (that's Graphify-style tooling;
  okfsmith ingests *documents*, not code),
- executing attested computations (OKF fixes the computation's *interface*,
  not its packaging or execution),
- already-clean markdown pipelines where a simpler tool suffices,
- general document search (build the bundle first, then use the MCP
  `search` tool on the finished bundle).
