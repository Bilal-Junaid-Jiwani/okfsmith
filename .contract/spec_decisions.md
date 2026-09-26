# OKF v0.2 — Spec Decisions (implementer cheat-sheet)

**Source:** the live `SPEC.md` in `GoogleCloudPlatform/open-knowledge-format`
(canonical repo), fetched 2026-09-26. The old `knowledge-catalog/okf/` copy is a
**frozen snapshot — ignore it.** Every rule below cites a spec section; nothing
here is invented. If this sheet and the live spec ever disagree, the spec wins.

**Spec version:** 0.2. The document is self-contained; §13 summarizes v0.1→v0.2.

---

## 1. Bundle model (§2, §3)

- A **bundle** is a directory tree of markdown files — the unit of distribution.
- Distribution forms (§3): git repo (**recommended**, gives history/attribution/diffs),
  tarball/zip, or a subdirectory of a larger repo.
- A **concept** is one unit of knowledge = one markdown document.
- Directory layout is domain-independent; producers organize freely.
- The validator takes an **explicit bundle-root path** argument. `index.md` at that
  root is the "bundle-root index.md" (§8, §12).

## 2. Concept ID rule (§2)

- **Concept ID = the file's path within the bundle, minus the `.md` suffix.**
  `finance/revenue.md` → `finance/revenue`.
- Reserved files (`index.md`, `log.md`) are **not** concepts and get no concept ID.
- Non-`.md` files (`.py`, `.sql`, …) are **not** concept documents (§3.1:
  "All other `.md` files are concept documents") — the validator ignores them entirely.

## 3. Reserved filenames (§3.1, §8, §9)

| Filename | Purpose | Frontmatter allowed? |
|---|---|---|
| `index.md` (any level) | Directory listing, progressive disclosure (§8) | **No** — except bundle-root `index.md` MAY carry `okf_version` only (§12) |
| `log.md` (any level) | Chronological update history (§9) | **No** |

- Reserved at **any level** of the hierarchy; MUST NOT be used for concept documents.
- Filenames are matched literally and case-sensitively: `Index.md` is *not* reserved
  and would be treated as a concept document (locked decision).

## 4. Frontmatter schema (§4.1)

Block delimited by `---` on its own line at the **start of the file**, closed by
`---` on its own line.

**Required — exactly one key:**

- `type`: short string identifying the kind of concept (e.g. `BigQuery Table`,
  `Metric`, `Playbook`, `Attested Computation`). Type values are **not** centrally
  registered; consumers MUST tolerate unknown types. A concept carrying just
  `type` is fully conformant.

**Recommended:**

- `title` — display name. If omitted, consumers MAY derive it from the filename.
- `description` — one sentence; used by index generators, search snippets, previews.
- `resource` — URI identifying the underlying asset. **Absent for abstract ideas**
  (its absence is normal, not a defect).
- `tags` — YAML list of short strings.

**Optional v0.2 families:** `sources[]` (+ `usage_window`), `generated`, `verified`,
`status`, `stale_after` (§5); `runtime`, `parameters`, `computation`, `executor`,
`attester` for Attested Computation (§10).

**Extensions:** producers MAY add any keys; consumers SHOULD preserve unknown keys
on round-trip and **MUST NOT reject** documents with unrecognized fields (§4.1).
`okf_version` on a *concept* file is not the declared location (§12) — ignore it
silently (locked decision).

**Locked parsing decisions:**
- No frontmatter block, or YAML that fails to parse → **E001**.
- Frontmatter parses but is not a YAML mapping, or `type` is missing / null /
  empty / whitespace-only → **E002** (it cannot "contain a non-empty `type`").
- `type` given as a non-string scalar (e.g. a number) is accepted and coerced to
  string; only empty/missing is an error.

## 5. Provenance: `sources` (§5.1)

Each `sources` entry:

- `resource`: **REQUIRED within an entry.** An absolute URL, a bundle-relative
  path, a `references/` path — **or a scope descriptor** (e.g.
  `all queries in BigQuery project X`) that is *not* a path (§5.1, §6.2).
- `id`: optional, but **SHOULD be present when the body cites the source**.
  Stable join key for per-claim attribution (see below).
- `title`: optional human-readable label.
- Credibility signals (all optional): `author` (actor convention, §7),
  `usage_count` (exercises of `resource` over `usage_window`), `last_modified`
  (when the *source* changed — distinct from `generated.at`, when the *concept*
  was written).
- `usage_window`: written **once as a sibling of `sources`**, framing every
  `usage_count` with `{ from, to }`. One entry MAY carry its own `usage_window`
  to override the shared one.

**Signal philosophy (do not re-litigate):** OKF records objective signals, **not**
a credibility score — scores are subjective, unportable, and go stale. Trust
tiers are *inferred* (§5.3), never stored. `usage_count` is **coarse**: comparable
at alive-vs-dead / order-of-magnitude level and against a source's own history,
never as a precise cross-kind ranking. Consumers read it as liveness/trend, not
a score. The validator treats `usage_count` as opaque informational data (locked).

**Lineage:** expressed through links, not a dedicated field. A consumer MAY recurse
into a source's own `sources` when `resource` points at another OKF concept.
Deeper/external lineage (`derived_from`, data lineage) is **out of scope** for v0.2.

**Per-claim attribution (§4.2, §5.1):** a claim cites a source with a markdown
footnote whose **label is a `sources[].id`**:

```markdown
The `events_` table is sharded daily as `events_YYYYMMDD`.[^ga4-schema]

[^ga4-schema]: GA4 BigQuery Export schema
```

- The label is the join key into `sources`; consumers resolve through the matching
  entry, not the footnote prose.
- Labels are keyed, **never positional** (`sources[0]`), because agents reorder lists.
- Validator: a footnote *reference* `[^id]` with no matching `sources[].id` →
  **W004**. Duplicate `sources[].id` within one concept → **W015**.
  Footnote *definitions* are prose and are not checked.

## 6. Trust: `generated` and `verified` (§5.2)

```yaml
generated: { by: reference_agent/gemini-2.5-pro, at: 2026-06-20T22:53:05Z }
verified:
  - { by: human:ahormati, at: 2026-06-25T09:00:00Z }
  - { by: process:finance-nightly, at: 2026-06-26T02:00:00Z }
```

- `generated.by`: **REQUIRED within `generated`** — an actor (§7). Missing → **W009**.
- `generated.at`: ISO 8601 datetime of the content's **last meaningful change**
  ("meaningful" is producer-defined; the validator checks format only — locked).
- `verified`: list of `{ by, at }` verification events. Multiple entries = independent
  checks. "How recently" = the latest `at`.
- `verified` is **independent** of `generated.at`: content can change without
  re-confirmation and vice versa.
- **Bare mapping = one-element list.** `verified: { by: human:x, at: ... }` (no dash)
  is legal; consumers **MUST** normalize it before anything else (§5.2, §11).
  A `verified` entry missing `by` → **W009**.
- **All timestamps in OKF** (every timestamp-valued key) are ISO 8601 with an
  **explicit UTC offset**, e.g. `2026-06-30T14:00:00Z` (§5 intro). Naive or
  unparseable datetimes → **W011** (covers `generated.at`, `verified[].at`,
  `sources[].last_modified`, `usage_window.from/to`, `stale_after`, legacy
  `timestamp`).
- Both families are optional; absence is meaningful, never a rejection (§5 intro).

## 7. Trust tiers (§5.3) — derived, never stored

Derived from `verified`, lowest to highest:

| Condition | Tier |
|---|---|
| No `verified` key (or `verified: []`) | **unverified** |
| `verified` by non-`human:` actors only | **machine-confirmed** |
| `verified` by any `human:` actor | **human-reviewed** |

Locked decisions:
- `verified: []` (empty list) counts as no verification → **unverified**.
- Classification keys **only** off the `human:` prefix (§5.3, §7). Any other prefix —
  including the spec's own `author: team:ga4-docs` example (§5.1) — is non-human.
- A concept with no trust frontmatter is still consumable; consumers MUST NOT
  reject it. Tiers are **advisory signals, not access control**.
- The bare-mapping `verified` form MUST be normalized to a list *before* tier
  derivation (§11).

## 8. Lifecycle: `status` and `stale_after` (§5.4, §5.5)

- `status: draft | stable | deprecated`. `draft` = not yet reviewed, possibly
  incomplete; `stable` = ready for consumption; `deprecated` = kept for links and
  history, no longer current. **Absent `status` ⇒ `stable`.**
  Unknown status value → **W014** (advisory; not a conformance error).
- `stale_after`: optional **absolute instant** (not a relative TTL).
  A concept is stale when `now >= stale_after` (compare in UTC). Stale content →
  informational **W006**; never an error.

## 9. Cross-linking and paths (§6)

**Links between concepts (§6.1):** standard markdown links, two forms —

- **Absolute (bundle-relative), recommended:** begins with `/`, interpreted relative
  to the bundle root. Stable when documents move within their subdirectory.
  ```markdown
  See the [customers table](/datasets/customers) for the join key.
  ```
- **Relative:** a standard markdown relative path, resolved from the linking file's
  directory (locked decision).
  ```markdown
  See the [neighboring concept](../datasets/customers).
  ```

- A link A→B asserts a **relationship**. The kind (parent/child, references,
  joins-with, depends-on) comes from the **surrounding prose, not the link**.
  Graph consumers treat all links as **directed edges of an untyped relationship**
  (locked: the validator performs no relation typing — the spec defines none).
- **Consumers MUST tolerate broken links** (§6.1, §11): a target missing from the
  bundle is not malformed — it may be not-yet-written knowledge. Validator emits
  advisory **W001**, never an error.

**Locked link-resolution rules (validator):**
- Resolution candidates for a target: `<target>` and `<target>.md`
  (concept IDs omit the suffix, per §2 and the §8 index examples).
- Strip URL fragments (`#...`) and query strings before resolving.
- `http(s)://` (and other-scheme) URLs are external — not bundle links, not checked.
- Path-valued *fields* (`resource`, `sources[].resource`, `computation`,
  `executor.resource`, `attester.resource`) are **not** link-checked: per §6.2 they
  may be absolute URLs, bundle-relative paths, relative paths, or (for
  `sources[].resource`) non-path scope descriptors, and may legitimately point at
  not-yet-created files (locked decision).

**The `references/` convention (§6.3):** a subdirectory conventionally mirroring
external material, run instructions, or code as first-class concepts
(e.g. `references/attesters/revenue.py`). A naming convention, **not** a
requirement — the validator requires nothing of it.

## 10. Actor convention (§7)

Fields recording an identity (`generated.by`, `verified[].by`, `sources[].author`)
use one convention:

- `<agent>/<model>` for agents and tools — e.g. `reference_agent/gemini-2.5-pro`
- `human:` for a person — e.g. `human:ahormati`
- `process:` for an automated process — e.g. `process:finance-nightly`

Trust-tier classification keys off the `human:` prefix, so producers **MUST** use
it for hand-authored or human-confirmed content.

## 11. Index files (§8)

- An `index.md` MAY appear in **any directory, including the bundle root**, for
  **progressive disclosure** (see what's available before opening documents).
- **No frontmatter**, with exactly one exception: a bundle-root `index.md` MAY
  carry an `okf_version` key (§12). Locked: root index with any other frontmatter
  key → **E003**; non-root index with any frontmatter at all → **E003**.
- Body: one or more sections, each grouping entries under a heading:
  ```markdown
  # Section / Group Heading

  * [Title 1](title-1) - short description of item 1
  * [Title 2](title-2) - short description of item 2

  # Another Section

  * [Subdirectory](subdirectory) - short description of the subdirectory
  ```
- Entry format: `* [Title](path) - description`. Entries **SHOULD** include the
  description from the linked concept's frontmatter (SHOULD, not MUST).
- Producers MAY generate `index.md` automatically; consumers MAY synthesize one
  when absent (§11: missing `index.md` files are never a rejection reason).

**Locked validator decisions:**
- Only markdown-link entries are honored for reachability; other bullet/prose
  lines are ignored (no warning).
- An entry pointing at a **directory** covers all concepts beneath it.
- A concept not reachable from any index entry (directly or via a directory
  entry) → advisory **W002** (orphan). Reachability is about *index* entries;
  body links do not confer reachability.

## 12. Log files (§9)

- A `log.md` MAY appear at **any level** to record that scope's change history.
- Format: a flat list of **date-grouped entries, newest first**:
  ```markdown
  # Directory Update Log

  ## 2026-05-22

  * **Update**: Added a BigQuery table reference for [Customer Metrics](...).
  * **Creation**: Established the [Dataplex Playbook](...).

  ## 2026-05-15

  * **Initialization**: Created foundational directory structure.
  ```
- **Date headings MUST use ISO 8601 `YYYY-MM-DD`** — a heading that is not a
  valid calendar date in that form → **E004**. (Locked: `^## \d{4}-\d{2}-\d{2}$`
  plus calendar validity.)
- "Newest first" is stated as the format; out-of-order date groups → advisory
  **W013** (locked).
- Log entries are prose; the leading bold word (`**Update**`, `**Creation**`,
  `**Deprecation**`) is **a convention, not a requirement** — the validator MUST
  NOT require it.
- No frontmatter in `log.md` (it's a reserved file; §3.1, §8/§9 structure).

## 13. Attested Computation (§10)

A concept of `type: Attested Computation` carries a **sanctioned way to compute
a value**, so a consumer can confirm the value was produced by running it.
Provenance (§5.1) answers "where did this claim come from"; attestation answers
"was this number produced the way we said it must be."

- **One computation = one standalone concept** (§10.1). Consumers link to it with
  a normal markdown link. Trust state is per computation (`verified`,
  `stale_after`, one attester each).
- **Contract fields** (top-level frontmatter, §10.2) — in addition to the §5 families:
  - `runtime`: **REQUIRED for this type.** Says how to run the computation (how
    executor/attester interpret it, what `parameters` mean). Examples: `bigquery`,
    `postgres`, `dbt`, `python`, `Looker`. Missing on an Attested Computation →
    advisory **W010** (locked: not one of the §11 hard rules, so a warning).
  - `parameters`: list of typed named holes the agent may fill; each
    `{ name, type, required }`. Binding semantics follow `runtime`.
  - `computation`: optional path (§6.2) to a file holding the computation.
    Absent ⇒ the body `# Computation` fence *is* the computation.
  - `executor`: how it runs. `resource` names run instructions/code;
    `receipt` declares the fields a run must return (e.g. `[job_id, executed_sql, result]`).
  - `attester`: the deterministic check. `resource` names code (**no LLM**) that
    takes a receipt and returns a verdict; meant to run consumer-side.
- **The computation itself** (§10.3), one of two ways:
  - **Inline:** a single fenced code block in the body under `# Computation`.
  - **File:** `computation:` set to a path, body fence omitted.
- The agent MAY only supply *values* for declared `parameters`; it MUST NOT
  author or edit the computation. Binding is the consumer's job; the attester
  independently re-derives the binding and compares against what ran.
- **What sits behind a `resource`** (Skill, script, container) is a **packaging
  choice — OKF fixes the interface, not the packaging** (§1 non-goals, §10.2).
  The validator does not validate packaging (locked).
- **Verification vs attestation** (§10.6): `verified` confirms the *definition*
  still matches policy (doc-level, slow, recorded in the bundle); attestation
  confirms a single *run* produced the value the sanctioned way (per-call,
  runtime, **not stored in the bundle**).
- **Informative only** (§10.5): the runtime flow (discover → load → parameterize →
  execute → attest → gate). Receipts are runtime artifacts, never bundle content.

## 14. Conformance (§11) — the exact 3 hard rules

A bundle is **conformant** with OKF v0.2 iff **all** of:

> 1. Every non-reserved `.md` file in the tree contains a parseable YAML
>    frontmatter block.
> 2. Every frontmatter block contains a non-empty `type` field.
> 3. Every reserved filename (`index.md`, `log.md`) follows the structure in
>    §8 and §9 respectively when present.

Plus consumer obligations the validator (as a consumer) MUST honor:

- MUST treat a bare `verified` mapping as a one-element list.
- MUST NOT reject a concept for missing any optional family.
- SHOULD derive trust tiers and staleness only from the fields specified here.
- MUST NOT reject a bundle for: missing optional frontmatter fields; unknown
  `type` values; unknown additional frontmatter keys; **broken cross-links**;
  missing `index.md` files.

Anything beyond the 3 hard rules is advisory → warnings, never errors.

## 15. Versioning (§12)

- This sheet covers OKF **0.2**. Minor bumps = backward-compatible additions;
  major bumps may break (renaming required fields, changing reserved filenames).
- Bundles MAY declare `okf_version: "0.2"` in a **bundle-root `index.md`
  frontmatter block — the only place frontmatter is permitted in an `index.md`**.
- `okf_version` value other than `"0.2"` → advisory **W007**; consumers SHOULD
  attempt best-effort consumption, not refuse.
- Intentionally deferred (do not design for these): receipt/verdict wire formats
  and attestation lifecycle; attester ABI/portability/sandboxing; attestation
  caching; semantic-layer templates (Looker/dbt model-and-binding equality).

## 16. v0.1 → v0.2 changes (§13)

v0.2 is a minor bump **except two deliberate breaking changes**:

1. **`timestamp` superseded by `generated.at`.** Last content change is now
   `generated: { by, at }`. Consumers **MAY fall back** to legacy `timestamp`
   when `generated` is absent. Validator: legacy `timestamp` → informational
   **W012**, never an error.
2. **Body `# Citations` list superseded by `sources`.** Provenance moves to
   frontmatter. Consumers **SHOULD** read `sources` and **MAY** still parse a
   legacy `# Citations` body list. Validator: `# Citations` heading with a list
   → informational **W012**, never an error.

Additive (absence = plain v0.1 concept): `sources` + credibility signals
(`author`, `usage_count`, `last_modified`) + `usage_window` sibling; `generated`,
`verified`; `status`, `stale_after`; the `Attested Computation` type with
`runtime`/`parameters`/`computation`/`executor`/`attester`; the `# Computation`
conventional heading; the actor convention.

## 17. Ambiguities the builder must decide (locked resolutions)

These are points where the spec is silent or leaves judgment to the producer.
Each resolution below is **locked** — implement exactly this.

| # | Ambiguity | Locked resolution |
|---|---|---|
| A1 | Typed relations between concepts | The spec defines **none** (§6.1: links are untyped directed edges; kind comes from prose). The validator performs no relation typing. |
| A2 | Trust/credibility scores | The spec **records signals, never scores** (§5.1). The validator derives tiers only (§5.3) and never computes or stores a score. |
| A3 | Tag aggregation | No tag file format exists (§3); tag views are synthesized at consumption. The validator may build an in-memory tag index but never requires one. |
| A4 | `generated.at` "last meaningful change" | "Meaningful" is producer-defined (§5.2). The validator checks ISO-8601-with-offset format only (W011), never freshness semantics. |
| A5 | `usage_count` coarseness | Coarse, order-of-magnitude signal (§5.1); no cross-kind comparison. The validator treats it as opaque informational data — no validation, no warning. |
| A6 | `verified: []` (empty list) | Counts as no verification → tier **unverified** (§5.3 "No `verified` key"). |
| A7 | Non-standard actor prefixes (e.g. spec's own `author: team:ga4-docs`, §5.1) | Non-human for tier derivation. Classification keys **only** off the `human:` prefix (§5.3, §7). |
| A8 | `verified` entry missing `by` | Cannot classify the verifier → **W009** (same code as `generated` missing `by`). |
| A9 | `okf_version` on a concept file | Not the declared location (§12). Per the extensions clause (§4.1: MUST NOT reject unrecognized fields) it is **silently ignored**. |
| A10 | `Index.md` / `LOG.md` casing | Reserved names are matched literally and case-sensitively (§3.1). `Index.md` is a concept document and needs frontmatter. |
| A11 | Index entries that aren't markdown links | Ignored for reachability (no warning). Only `[...](...)` entries confer reachability. |
| A12 | Reachability vs body links | **W002** orphan = not reachable from any *index* entry (directly or via a directory entry). Body links between concepts do not confer reachability. |
| A13 | `log.md` newest-first | Stated as the format (§9); out-of-order groups → **W013** (advisory), not E004. |
| A14 | Staleness clock | `now >= stale_after` compared in UTC → **W006**. Never an error. |
| A15 | Executor/attester packaging | Interface only, not packaging (§1, §10.2). The validator checks that `executor.resource` / `attester.resource` are present strings at most; it never validates what they point to. |
| A16 | Unknown `status` value | → **W014** (advisory). Absent ⇒ `stable` (§5.4). |
| A17 | Non-mapping or unparseable `sources`/`generated`/`verified` values | Malformed structures → **W011** (format) family; missing REQUIRED sub-keys (`sources[].resource`, `generated.by`) → **W008** / **W009**. Never errors. |
| A18 | `type` given as non-string scalar | Accepted, coerced to string. Only missing/null/empty/whitespace-only → **E002**. |

---

## 18. Decisions locked — validator rule codes (implement verbatim)

### Errors (E-codes) — bundle NON-conformant. Map 1:1 to §11's three hard rules.

| Code | Name | Fires when | Spec |
|---|---|---|---|
| **E001** | `no-frontmatter` | A non-reserved `.md` file has no frontmatter block, or its YAML fails to parse | §11.1, §4.1 |
| **E002** | `empty-type` | Frontmatter is not a YAML mapping, or `type` is missing / null / empty / whitespace-only | §11.2 |
| **E003** | `bad-index` | `index.md` frontmatter violation: non-root `index.md` with *any* frontmatter; bundle-root `index.md` with frontmatter keys beyond `okf_version` | §11.3, §8, §12 |
| **E004** | `bad-log` | `log.md` has a `## ` heading that is not a valid calendar date in ISO `YYYY-MM-DD` form | §11.3, §9 |

### Warnings (W-codes) — advisory only. A bundle with warnings is still conformant.

| Code | Name | Fires when | Spec |
|---|---|---|---|
| **W001** | `broken-link` | A markdown body link target resolves to no file in the bundle (candidates: `<target>`, `<target>.md`; strip fragments/queries; skip external URLs; path-valued *fields* are never link-checked) | §6.1 |
| **W002** | `orphan-concept` | A concept is not reachable from any `index.md` link entry, directly or via a directory entry | §8 |
| **W003** | `missing-recommended` | `title` or `description` absent (message names the field). `resource`/`tags` absence is never warned — explicitly normal for abstract ideas | §4.1 |
| **W004** | `footnote-unresolved` | A body footnote reference `[^id]` has no matching `sources[].id` | §5.1 |
| **W005** | `source-missing-id` | A `sources` entry lacks `id` | §5.1 |
| **W006** | `stale-content` | `now >= stale_after` (UTC comparison). Informational | §5.5 |
| **W007** | `unknown-okf-version` | Bundle-root `index.md` declares `okf_version` other than `"0.2"`. Best-effort consumption continues | §12 |
| **W008** | `source-missing-resource` | A `sources` entry lacks its REQUIRED `resource` | §5.1 |
| **W009** | `actor-missing-by` | `generated` lacks REQUIRED `by`, or a `verified` entry lacks `by` | §5.2 |
| **W010** | `attested-missing-runtime` | `type: Attested Computation` without `runtime` (REQUIRED for this type) | §10.2 |
| **W011** | `malformed-datetime` | A timestamp-valued key (`generated.at`, `verified[].at`, `sources[].last_modified`, `usage_window.from/to`, `stale_after`, legacy `timestamp`) is not ISO 8601 with an explicit UTC offset | §5 intro, §5.2, §5.5 |
| **W012** | `legacy-v01-fields` | Legacy `timestamp` field present, or a body `# Citations` list present. Informational; v0.1 bundles remain consumable | §13.1 |
| **W013** | `log-out-of-order` | `log.md` date groups are not newest-first | §9 |
| **W014** | `unknown-status` | `status` is not one of `draft` / `stable` / `deprecated` | §5.4 |
| **W015** | `duplicate-source-id` | Two `sources` entries in one concept share the same `id` (the footnote join key must be unique) | §5.1 |

### Design principles (locked)

1. **Exactly 4 error codes, 15 warning codes.** Errors map only to §11's three
   hard rules; everything else is a warning.
2. **Warnings never affect conformance.** Exit code / pass-fail derives from
   `errors[]` alone.
3. **Normalization before derivation:** bare-mapping `verified` → one-element
   list, *then* trust-tier derivation (§5.2, §11).
4. **Derive tiers/staleness only from the specified fields** (§11): `verified`
   (+ `human:` prefix) for tiers; `stale_after` vs now for staleness.
5. **Deterministic messages:** each finding carries `{code, file, message, spec}`.
   `file` is the bundle-relative path.
6. **No invented checks:** the validator MUST NOT add hard errors beyond E001–E004
   (e.g. never error on missing optional fields, unknown types/keys, broken
   links, missing indexes, unknown `status`, or legacy v0.1 fields).

### Fixture coverage map

| Fixture | Exercises |
|---|---|
| `fixtures/valid/` | Clean run: `errors[]`, `warnings[]` empty; root `okf_version` exception; subdir indexes; proper `log.md`; `sources[]` + signals + `usage_window`; `generated`; `verified` list **and** bare-mapping normalization; Attested Computation; footnote attribution; bundle-relative links; non-`.md` file ignored; trust tiers (`finance/revenue` human-reviewed, `finance/profit` machine-confirmed, `incidents/playbook` unverified, `computations/revenue` human-reviewed) |
| `fixtures/err-no-frontmatter/` | E001 |
| `fixtures/err-empty-type/` | E002 (empty and missing variants) |
| `fixtures/err-bad-index/` | E003 (root index with extra key; subdir index with frontmatter) |
| `fixtures/err-bad-log/` | E004 (non-ISO date heading) |
| `fixtures/warn-dead-link/` | W001 |
| `fixtures/warn-orphan/` | W002 |
| `fixtures/legacy-v01/` | W012 ×2 (`timestamp`, `# Citations`); no errors |
| `fixtures/trust-tiers/` | Tier derivation: unverified / machine-confirmed / human-reviewed (bare mapping) / human-reviewed (mixed); no errors or warnings |

W003–W011, W013–W015 have no dedicated fixtures yet — the validator engineer
should add fixtures for them following the same `EXPECTED.json` schema
(`{fixture, description, errors[], warnings[], trust_tiers?}` with findings as
`{code, file, message, spec}`).
