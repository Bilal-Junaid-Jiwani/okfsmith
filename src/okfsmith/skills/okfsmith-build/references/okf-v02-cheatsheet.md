# OKF v0.2 — Condensed Reference

Distilled from `okfsmith/.contract/spec_decisions.md`. The canonical
GoogleCloudPlatform/open-knowledge-format `SPEC.md` wins on any disagreement.

## Bundle model (§2, §3)

- A **bundle** is a directory tree of markdown files; a **concept** is one
  knowledge unit = one markdown document.
- Distribution forms: git repo (recommended), tarball/zip, or a subdirectory.
- **Concept ID** = file path within the bundle minus the `.md` suffix
  (`finance/revenue.md` → `finance/revenue`).
- Non-`.md` files are not concepts and are ignored entirely.

## Reserved filenames (§3.1, §8, §9)

| File | Purpose | Frontmatter? |
|---|---|---|
| `index.md` (any level) | Directory listing, progressive disclosure | **No** — except bundle-root `index.md` may carry `okf_version` only (§12) |
| `log.md` (any level) | Chronological update history | **No** |

Matched literally and case-sensitively: `Index.md` is a concept, not reserved.

## Frontmatter schema (§4.1)

Delimited by `---` at the very start of the file, closed by `---`.

**Required — exactly one key:** `type` (short string naming the concept kind,
e.g. `Metric`, `Playbook`, `Attested Computation`). Unknown types are legal;
consumers must tolerate them. A concept carrying only `type` is conformant.

**Recommended:** `title`, `description` (one sentence), `resource` (URI of the
underlying asset; absent for abstract ideas — normal, not a defect),
`tags` (list of short strings).

**Optional v0.2 families:** `sources[]` (+ `usage_window`), `generated`,
`verified`, `status`, `stale_after` (§5); `runtime`, `parameters`,
`computation`, `executor`, `attester` for Attested Computation (§10).

**Extensions:** producers may add any keys; consumers must not reject
unrecognized fields and should preserve them on round-trip.

## Provenance: `sources` (§5.1)

```yaml
sources:
  - id: ga4-schema
    resource: https://developers.google.com/analytics/bigquery/export-schema
    title: GA4 BigQuery Export schema
    author: team:ga4-docs        # actor convention, see below
    usage_count: 5000           # coarse liveness signal, never a score
    last_modified: 2026-05-30T00:00:00Z
usage_window: { from: 2026-06-01T00:00:00Z, to: 2026-06-30T00:00:00Z }
```

- `sources[].resource` is required *within* an entry (URL, bundle-relative
  path, `references/` path, or a non-path scope descriptor).
- `id` is the join key for per-claim footnotes: `...daily as
  events_YYYYMMDD.[^ga4-schema]`. Footnote labels are keyed, never positional.
- `usage_window` is written once as a sibling of `sources`.

## Trust: `generated` / `verified` (§5.2) and tiers (§5.3)

```yaml
generated: { by: reference_agent/gemini-2.5-pro, at: 2026-06-20T22:53:05Z }
verified:
  - { by: human:ahormati, at: 2026-06-25T09:00:00Z }
  - { by: process:finance-nightly, at: 2026-06-26T02:00:00Z }
```

- `generated.by` is required within `generated`; `generated.at` is last
  meaningful content change ("meaningful" is producer-defined).
- Bare mapping = one-element list: `verified: { by: human:x, at: ... }`
  (no dash) is legal and must be normalized to a list first.
- Trust tiers are **derived, never stored**:

| Condition | Tier |
|---|---|
| No `verified` key (or `verified: []`) | `unverified` |
| `verified` by non-`human:` actors only | `machine-confirmed` |
| `verified` by any `human:` actor | `human-reviewed` |

- **All timestamps** use ISO 8601 with an explicit UTC offset (`...Z`).
- **Actor convention (§7):** `<agent>/<model>`, `human:` (person),
  `process:` (automation). The `human:` prefix drives trust tiers.

## Lifecycle (§5.4, §5.5)

- `status: draft | stable | deprecated`; absent ⇒ `stable`.
- `stale_after`: absolute instant (not a TTL); stale when `now >= stale_after`.

## Linking (§6)

- **Bundle-relative absolute** (recommended): `[customers](/datasets/customers)`
  — stable when documents move within their subdirectory.
- **Relative:** `[neighbor](../datasets/customers)` resolved from the linking
  file's directory.
- Links are directed edges of an **untyped relationship** (kind comes from
  prose; there is no relation typing).
- **Broken links are warnings, never errors.** Path-valued fields
  (`resource`, `sources[].resource`, ...) are never link-checked.
- `references/` subdirectory: convention for mirroring external material,
  run instructions, or code as first-class concepts.

## Index files (§8)

- One per directory (including bundle root) for progressive disclosure:
  ```markdown
  # Finance

  * [Customer Orders](finance/revenue) - One row per completed order.
  * [Reference material](references) - Mirrored external docs.
  ```
- Entry format: `* [Title](path) - description`. A directory entry covers
  everything beneath it.
- Missing `index.md` files are never a rejection reason.

## Log files (§9)

- Date-grouped entries, newest first; date headings **must** be valid
  ISO `YYYY-MM-DD` calendar dates:
  ```markdown
  # Directory Update Log

  ## 2026-05-22

  * **Update**: Added the [Customer Metrics](...) table.
  ```
- The leading bold word (`**Update**`, `**Creation**`) is a convention,
  not a requirement.

## Attested Computation (§10)

One computation = one standalone concept of `type: Attested Computation`.
Provenance answers "where did this claim come from"; attestation answers
"was this number produced the sanctioned way".

- `runtime` required for this type (e.g. `bigquery`, `postgres`, `python`).
- `parameters`: typed named holes the agent may fill — agents supply *values*
  only, never author or edit the computation.
- `computation`: path to the code file; absent ⇒ the `# Computation` fenced
  block in the body *is* the computation.
- `executor` (how it runs; `receipt` declares returned fields),
  `attester` (deterministic, non-LLM check of a run receipt, consumer-side).
- Receipts are runtime artifacts — never stored in the bundle.

## Conformance (§11) — the only hard rules

A bundle is conformant iff all three hold; everything else is advisory:

1. Every non-reserved `.md` file has a parseable YAML frontmatter block.
2. Every frontmatter block contains a non-empty `type` field.
3. Every `index.md`/`log.md` follows the §8/§9 structure.

MUST NOT be rejected: missing optional fields, unknown types, unknown extra
keys, broken cross-links, missing `index.md` files.

## Versioning (§12)

- Bundles may declare `okf_version: "0.2"` in the **bundle-root** `index.md`
  frontmatter — the only permitted frontmatter in an `index.md`.
- v0.1 → v0.2 breaking changes: `timestamp` superseded by `generated.at`;
  body `# Citations` list superseded by frontmatter `sources`.
