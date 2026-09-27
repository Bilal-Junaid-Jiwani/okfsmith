---
title: Temporal model
eyebrow: User guide
description: Time-aware knowledge — validity windows (valid_from / valid_until), supersession chains (supersedes), as-of queries, and how freshness interacts with trust tiers.
---

## Knowledge has a shelf life

A refund policy valid until 2025 is still *in* your bundle in 2026 — deleting it would destroy history, but surfacing it as current would be wrong. okfsmith's temporal model keeps every version and ranks them by **currency**:

1. **Validity window** — `valid_from` / `valid_until` in a concept's frontmatter.
2. **Supersession** — `supersedes: <older-concept-id>` declares a replacement chain.
3. **Trust tier** — human-reviewed > machine-confirmed > unverified (as before).
4. **`last_verified` recency** — newest first, but only as a tie-breaker.

Within one currency group the existing BM25 score still picks the best text match; trust and recency only break ties. A human-reviewed concept never loses to an unverified one *just* because the unverified one is newer — but it does lose to a concept that explicitly supersedes it.

```bash
# "What was our refund policy in June 2025?"
okfsmith search ./kb "refund policy" --as-of 2025-06-01

# Include superseded versions (hidden by default, never deleted)
okfsmith search ./kb "refund policy" --include-superseded
```

## Frontmatter fields

All four fields are optional. Malformed values never crash anything — they produce the advisory warnings W016–W020 instead.

```yaml
---
id: policy/refunds-v2
title: Refund policy v2
valid_from: 2025-07-01        # ISO-8601 date or datetime; naive = UTC
valid_until: 2026-06-30       # date-only covers the whole day through 23:59:59 UTC
supersedes: policy/refunds-v1 # id (or list of ids, max 100) this concept replaces
last_verified: 2026-01-15     # when a human/agent last confirmed this is right
---
```

**Semantics:**

- `valid_from` / `valid_until` define the window in which the concept is *current*. A concept queried before `valid_from` is **future**; after `valid_until` it is **expired**. Out-of-window concepts are **demoted, not hidden** — they still appear in results and lists, marked in the `Valid` column.
- `supersedes` links a concept to the older concept(s) it replaces. The newest *valid* concept at the head of the chain wins; superseded concepts are **hidden from search by default** (shown last with `--include-superseded`) and marked `superseded→<id>` in text output. They are never deleted.
- `last_verified` records freshness. Within the same validity + trust group, more recently verified concepts rank first.

**Cycle safety:** if two concepts supersede each other (validator warning W019), retrieval treats the cycle as unresolved — both concepts stay visible at their own validity instead of hiding each other.

## As-of queries

`--as-of <ISO-8601 date or datetime>` replays retrieval at that instant: validity windows and supersession chains are evaluated *then*, not now. Useful for audits ("what did we believe in Q2?") and for testing policy changes before they take effect.

```bash
okfsmith search ./kb "refund policy" --as-of 2025-06-01 --format json
```

The JSON envelope always reports the instant used and how many superseded results were hidden:

```json
{
  "query": "refund policy",
  "as_of": "2025-06-01T00:00:00+00:00",
  "results": [ … ],
  "count": 1,
  "superseded_hidden": 1
}
```

## Where temporal status shows up

| Command | Surface |
|---|---|
| `search` | `Valid` column (`expired` / `future` / `superseded→<id>`); `--as-of`, `--include-superseded`; JSON rows carry `temporal_status` and `superseded_by` |
| `list` | `Valid` column (`—` for concepts with no temporal fields, `current` / `expired` / `future` / `superseded` otherwise); JSON `temporal_status` |
| `read` | One-line `[temporal: …]` badge under the concept when it has temporal data or is superseded; JSON `temporal_status` |
| `validate` | Advisory warnings W016–W020 (never affect conformance) |
| chat / MCP | The shared search engine applies the same ranking — temporal behavior is identical everywhere |

## Sync preserves temporal metadata

When `sync` re-ingests a source whose concepts keep the same ids, their temporal frontmatter (`valid_from`, `valid_until`, `supersedes`, `last_verified`) is carried over onto the new versions; values already present in the source win. Concepts that are renamed or restructured (new ids) intentionally start fresh — okfsmith never guesses which new concept inherits an old one's history, and it never auto-stamps `supersedes` (that claim belongs to the source or to you).
