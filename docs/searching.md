# Searching a bundle

`okfsmith search` is full-text search over everything in a bundle —
titles, descriptions, tags, and bodies — ranked with BM25, the classic
information-retrieval scoring function. It is the same engine that powers
the MCP server's `search` tool and the chat REPL's `/search`, so all three
rank concepts identically.

## Why BM25

The old ranking was naive substring counting: a word in a title earned
3 points, a word in a body earned 1 point, and that was it. No term
weighting, no stemming ("running" never matched "run"), no phrases, no
exclusions — and there was no way to search from the terminal at all.

The BM25 engine fixes that with:

- **Term weighting.** A rare word like `kerberos` moves a concept to the
  top; a ubiquitous word like `the` barely nudges it.
- **Stemming.** `running`, `runs`, and `run` all match the same token.
- **Phrases and exclusions.** `"knowledge graph"` matches only adjacent
  words; `-deprecated` removes every concept mentioning `deprecated`.
- **No new dependencies.** The whole engine is stdlib-only, like the
  validator — it runs anywhere okfsmith runs, offline.

## The command

```bash
okfsmith search BUNDLE QUERY
```

The bundle is the first positional argument, the query is the second.
Quote multi-word queries so the shell passes them as one argument:

```bash
okfsmith search ./kb "database migrations"
okfsmith search ./kb -n 5 --format json "billing -refunds"
```

| Option | What it does |
|---|---|
| `--limit N`, `-n N` | Return at most `N` results (default 10). Must be ≥ 1, otherwise exit 2. |
| `--format text\|json` | Rich table (default) or machine-readable JSON. |
| `--tier TIER` | Only concepts with this trust tier (`unverified`, `machine-confirmed`, `human-reviewed`). |
| `--type TYPE` | Only concepts of this type. Same semantics and validation as `list`. |

Text output is a rich table — `Score | ID | Type | Title | Tier` —
followed by an `N result(s)` line. IDs are never truncated, so they are
copy-paste safe into `okfsmith read BUNDLE ID`. When nothing matches, the
command exits 0, prints `0 result(s)`, and prints a hint to stderr. An
empty or blank query is a usage error (exit 2). Expected failures print
`error [CODE]:` with a hint and never a traceback.

## Query syntax

The query language has three ingredients:

```bash
okfsmith search ./kb "exact phrase" -excluded term
```

- **Bare terms** (`billing`, `oauth`) match after tokenizing — case is
  ignored and stemming applies.
- **Phrases** (`"knowledge graph"`) match only when the words appear
  *adjacent*, in order, after tokenizing.
- **Exclusions** (`-deprecated`) remove any concept whose text contains
  the term.

An unbalanced quote never errors: the rest of the query is simply treated
as a phrase.

## How the tokenizer works

Every concept's text — and your query — goes through the same pipeline:

1. **Lowercase.**
2. **Split on non-alphanumeric runs.** Punctuation and whitespace become
   boundaries, so `user-profile` yields `user` and `profile`.
3. **Drop stopwords.** About 40 common English words (`the`, `and`, `of`,
   `is`, …) are removed so they can't dilute the scores.
4. **Suffix stemming.** A small deterministic stemmer normalizes
   inflections: `sses→ss`, `ies→i`, and `ing`/`ed`/`s` stripping with
   length guards. `running`, `runs`, and `run` all become `run`.

Tip: search the stem you mean. `okfsmith search ./kb migrate` finds
`migration`, `migrating`, and `migrated` alike.

## Field weighting

Not every match is equal. Scores come from per-field term frequencies
weighted like this:

| Field | Weight | Rationale |
|---|---|---|
| Concept id, title | ×3 | what the author called it matters most |
| Description, tags | ×2 | deliberate metadata |
| Body | ×1 | the long tail |

So a concept *titled* "Billing retries" outranks a concept that merely
mentions billing retries once in passing, and a query term that appears
in many concepts contributes less to each score than a rare term.

The BM25 parameters are the standard `k1=1.2, b=0.75`. Results sort by
score descending; ties break by concept id, so the ordering is
deterministic across processes and runs.

## JSON output

```bash
okfsmith search ./kb "billing retries" --format json
```

```json
{
  "query": "billing retries",
  "results": [
    {"id": "api/billing-retries", "type": "Guide", "title": "Billing retries",
     "tier": "human-reviewed", "score": 7.42}
  ],
  "count": 1
}
```

Shape: top-level `query` (the raw query string), `results` (a list of
`id` / `type` / `title` / `tier` / `score` objects), and `count` (number of
results). Pipe it to `jq` in scripts.

## CLI / MCP / chat parity

The BM25 engine lives in one place and is used in three:

- **CLI** — `okfsmith search BUNDLE QUERY` builds an in-memory index per
  invocation (there is no persistent on-disk index in v1).
- **MCP server** — the `search` tool uses the same engine, so agent
  results match the CLI ordering exactly. The MCP server builds its index
  once at startup alongside `Bundle.load`.
- **Chat REPL** — `/search` and the REPL's retrieval path use the same
  engine through the `rank_concepts` compatibility shim (its old
  substring-scoring behavior is deprecated).

Given the same bundle and query, the CLI JSON order, the MCP `search`
order, and the chat `/search` order are identical.

## Examples

```bash
# Top 5 concepts about authentication, text output
okfsmith search ./kb -n 5 "authentication"

# Only human-reviewed guides mentioning "deployment"
okfsmith search ./kb --tier human-reviewed --type Guide "deployment"

# JSON for scripting: ids of everything matching the phrase
okfsmith search ./kb --format json '"error handling"' | jq '.results[].id'

# Find concepts about caching that are NOT about redis
okfsmith search ./kb "caching -redis"

# Verify the query found everything you expected, then read the winner
okfsmith read ./kb "$(okfsmith search ./kb --format json 'rate limits' | jq -r '.results[0].id')"
```

See also: [`list`](commands.md) for browsing with `--type`/`--tier`
filters, [`read`](commands.md) for full concepts, and the
[MCP server](mcp.md) for agent-side `search`.
