# Pipeline

`okfsmith ingest` runs every source through the same ordered stages. Each
stage's output is the next stage's input.

```
source file
  │ 1. COLLECT — gather files (recursive if asked), skip already-ingested
  │              via SHA-256 fingerprints
  ▼
  │ 2. PARSE — bytes → structured document (pages, text, tables, metadata)
  ▼
  │ 3. SECTION — split into titled sections (headings / page spans)
  ▼
  │ 4. EXTRACT — sections → concept drafts
  │              • --no-llm: one draft concept per section (offline, fast)
  │              • LLM: two-pass draft + critic; claims cite [^source-id]
  ▼
  │ 5. WRITE — concepts land as <bundle>/<source-slug>/<slug>.md with
  │            YAML frontmatter (type, title, trust, sources[], generated)
  ▼
  │ 6. INDEX/LOG — index.md refreshed, log.md appended (provenance)
```

## Trust tiers

Every concept carries a trust tier (see `okfsmith.core.spec.trust_tier`):

- `unverified` — produced by parsing/extraction, not yet checked.
- `machine-confirmed` — passed automated checks (validation, dedup/merge).
- `human-reviewed` — a person reviewed and approved it.

`--no-llm` ingests always start at `unverified`. Tiers are just frontmatter;
promote a concept by editing its file (or via the extract `human_review`
helper), then re-run `validate`.

## Dedup and merge

Re-ingesting an identical file is a no-op (SHA-256 manifest). Near-duplicate
concepts can be merged; tags and sources are normalized so a bare string
never becomes a character set and mixed-type tag lists never crash.

## Provenance

Each concept records `sources[]` (where its claims came from) and `generated`
(when/how it was produced). `log.md` keeps the bundle-level history: every
ingest appends an entry. Nothing is silently overwritten.
