---
title: Syncing sources
eyebrow: User guide
description: Keep a bundle in sync with changing sources — okfsmith sync only processes new, changed, renamed, or deleted files, with SHA-256 change detection, atomic resumable state, and watch mode.
---

## Sync your sources

`okfsmith sync` keeps a bundle aligned with the documents it came from.
Instead of re-ingesting everything after every edit, it fingerprints each
source with SHA-256 and processes only what actually changed:

```bash
okfsmith init ./kb

# First run: everything is new → ingested (same as ingest)
okfsmith sync ./kb ./docs --no-llm

# Later: only the edited file is re-processed
okfsmith sync ./kb ./docs --no-llm
```

Real output — the second run knows exactly what changed:

```text
                                Sync summary — kb
┏━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ File         ┃ Change    ┃ Concepts ┃ Detail                                  ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ docs/guide.md│ updated   │        1 │ 1 concept(s) (replaced 1)               │
│ docs/notes.md│ unchanged │        1 │ no changes                              │
└──────────────┴───────────┴──────────┴─────────────────────────────────────────┘
sync: 0 added, 1 updated, 0 renamed, 0 removed, 1 unchanged, 0 skipped, 0 failed → kb
```

> [!TIP]
> `sync` is the natural successor to `ingest` for living documents. Use
> `ingest` for the first import, `sync` for every update after that.

## What each change means

| Change | What `sync` does |
|---|---|
| `added` | Ingests the file — LLM or `--no-llm` path, exactly like `ingest`. |
| `updated` | Re-ingests and **replaces** the old concepts under the same ids. No `name-2` duplicates. |
| `renamed` | Detected by identical content hash at a new path. Concepts keep their ids and history; only the `resource` provenance is rewritten. |
| `removed` | The file is gone, so its concepts are deleted from the bundle. |
| `unchanged` | Skipped entirely — no parsing, no LLM calls, no writes. |
| `skipped` | The file would not ingest (unparseable, too small) — old concepts are kept. |
| `failed` | Something went wrong with this one file; the rest of the run continues. |

Additions are always applied **before** deletions, so a rename or a
replace can never leave the bundle momentarily empty.

> [!NOTE]
> **Temporal metadata survives re-ingest.** When an `updated` file's concepts
> keep the same ids, their `valid_from` / `valid_until` / `supersedes` /
> `last_verified` frontmatter is carried over onto the new versions (values
> already present in the source win). Renamed or restructured concepts — new
> ids — intentionally start fresh, and `sync` never auto-stamps `supersedes`.
> See [Temporal model](temporality.html).

## Watch mode

`--watch` keeps the sync running and re-scans on a timer. It's plain
stdlib polling — no extra dependencies, no filesystem hooks:

```bash
okfsmith sync ./kb ./docs --no-llm --watch --interval 10
```

- `--interval` is seconds between scans (default `5`, must be `> 0`).
- Unchanged cycles are cheap: an mtime+size fast path skips hashing, and
  identical hashes skip everything else — a quiet period costs almost nothing.
- Touching a file without changing its bytes does **not** trigger a re-sync.
- Ctrl-C stops cleanly after the current cycle finishes.

`--poll` is the default one-shot behavior made explicit; `--watch` and
`--poll` can't be combined, and neither can `--dry-run` with `--watch`.

## Dry runs and JSON

Preview what a sync would do without writing anything — no concepts, no
state file:

```bash
okfsmith sync ./kb ./docs --no-llm --dry-run
```

For scripts and CI, `--format json` emits a stable object:

```json
{
  "bundle": "kb",
  "sources": ["docs"],
  "dry_run": false,
  "resumed": false,
  "summary": {"added": 0, "updated": 1, "renamed": 0, "removed": 0,
              "unchanged": 1, "skipped": 0, "failed": 0},
  "files": [
    {"path": "/abs/docs/guide.md", "change": "updated", "old_path": null,
     "concepts": 1, "detail": "1 concept(s) (replaced 1)"}
  ]
}
```

`resumed: true` means the previous run was interrupted and this one picked
up where it stopped. Errors also come back as JSON
(`{"status": "error", "code": "...", "message": "...", "hint": "..."}`) when
`--format json` is set.

In `--watch` mode with `--format json`, the stream is **JSONL**: every
cycle emits exactly one compact JSON object on one line — one line per
cycle, no pretty-printing, so you can pipe it straight into `jq`:

```bash
okfsmith sync ./kb ./docs --no-llm --watch --interval 10 --format json | \
  jq -c '.summary'
```

## Safety guarantees

These are the rules `sync` never breaks:

- **Atomic state.** `<bundle>/.okfsmith/sync-state.json` is written via
  temp-file + rename after every file, so a crash can never corrupt it.
  `okfsmith validate` ignores the state file — it never affects conformance.
- **Symlink-safe state.** `sync` refuses to write through a symlinked
  `<bundle>/.okfsmith/`: the write is rejected with a clean
  `error [sync-refused]` before anything is written, so sync state
  can never land outside the bundle. A symlinked *bundle directory*
  itself is fine — it is resolved to its real path at startup, which is
  standard path resolution, not an attack.
- **Symlinked sources are skipped.** A source file that is a symlink is
  never followed — it is reported as a `skipped` row with a warning, so
  outside content can never be ingested through a link.
- **The bundle is never its own source.** Files under the bundle directory
  are excluded from source scanning (with a note), so syncing a tree that
  contains the bundle cannot self-ingest the bundle's concept files.
- **One sync at a time.** A per-bundle lock
  (`<bundle>/.okfsmith/sync.lock`, `O_CREAT | O_EXCL`) serializes
  concurrent syncs; a second concurrent sync exits with a clean
  `error [sync-locked]` instead of clobbering the state. Stale locks
  (dead process, or older than 10 minutes) are reclaimed automatically.
- **Resumable.** An interrupted run leaves `incomplete: true` in the state;
  the next run announces the resume and adopts already-ingested concepts
  instead of duplicating them. Sources that can never succeed without user
  action (e.g. a `.docx` without the `office` extra) are recorded as
  permanent per-source failures: they are reported every run, but they do
  not set the `incomplete` flag, so there is no resume nag for them.
- **Pre-flight on updates.** Before replacing a file's concepts, `sync`
  checks the new content would actually ingest. If it wouldn't (parse
  error, below the ~1000-char minimum, sectioning failure), the old
  concepts are kept and the file is reported `skipped` — updates never
  destroy knowledge.
- **Shared content is reference-counted.** Two files with identical bytes
  share one set of concepts; each concept tracks which state entries own
  it, and deleting a source drops the concepts only when the last owner
  disappears.
- **Scoped deletions.** `sync ./kb ./docs` only ever removes concepts
  that came from `./docs`. Other source trees are untouched.
- **No path escapes.** Concept deletion is confined to the bundle root,
  and concept ids can never traverse paths.
- **Per-file failures.** An unreadable file becomes a `failed` row, not a
  failed run. If *every* file fails, the exit code is 1
  (`error [sync-failed]`).

## The state file

Sync state lives at `<bundle>/.okfsmith/sync-state.json` — a JSON map of
absolute source paths to `{sha256, concepts, size, mtime_ns}`, plus
`version` and an `incomplete` flag. You can delete it at any time: the
next `sync` treats everything as new and adopts the concepts a previous
`ingest` already created, so nothing is duplicated.

> [!NOTE]
> Deleting the state file is also how you "reset" sync for a source tree
> — e.g. after reorganizing your documents.
