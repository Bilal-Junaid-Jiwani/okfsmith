# Changelog

All notable changes to okfsmith. Format follows Keep a Changelog; versions
follow SemVer.

## [Unreleased]

## [0.7.2] - 2026-10-05

### Added
- **Test coverage for the dashboard background-job manager:** the SSE
  job infrastructure (`okfsmith.dashboard.jobs` — `Job` lifecycle, step
  timing, terminal `{"status": ...}` publication, `JobManager`
  submit/evict/list, `sse_format`, `new_id`) previously had a single
  retention test; it is now pinned by `tests/test_dashboard_jobs.py`
  (22 tests), covering step-transition timing stamps, honest close-out
  of open steps on finish, queue wake-ups, bounded retention that never
  evicts active jobs, worker-exception → error-status conversion, and
  concurrent-emit thread safety.

## [0.7.1] - 2026-10-04

### Fixed
- **Shared section-concept link resolution for `okfsmith graph` and W001:**
  links written in a per-section concept (id `doc/section`) are relative to
  the source *document*, but only the dashboard's Explore graph applied that
  rule (0.5.1) — `okfsmith graph` reported such links as dead and `validate`
  raised a spurious W001 for them (e.g. `alpha/alpha-guide` linking
  `beta.md` when `beta` was split into per-section concepts). The rule now
  lives in the shared `okfsmith.links` resolver: on a miss, the target is
  retried at each ancestor level of the linking concept's id, and a target
  naming a whole document split into sections resolves to that document's
  primary section concept (section slug == file stem, else
  earliest-generated, else alphabetical). `okfsmith graph`, the dashboard
  graph, and W001 now agree; genuinely broken links are still dead, and
  links escaping the bundle root still resolve dead (the fallback never runs
  for them). Covered by `tests/test_links_section_fallback.py` (11 tests).

## [0.7.0] - 2026-10-03

### Added
- **Native Anthropic Messages API backend:** `--provider anthropic`
  (or just `ANTHROPIC_API_KEY` with no provider/base configured) now
  speaks Anthropic's native API directly — `POST
  https://api.anthropic.com/v1/messages` with the `x-api-key` and
  `anthropic-version` headers — instead of warning that the native API
  "cannot be called directly" and falling back to Ollama. This closes the
  last `TODO` in the codebase. System prompts are hoisted into the API's
  native `system` parameter, consecutive same-role turns are merged to
  satisfy the API's alternation rule, and reply text blocks are
  concatenated in order. Key precedence for the provider: `--api-key` →
  `OKFSMITH_API_KEY` → `ANTHROPIC_API_KEY` (provider-scoped, never leaks
  into other providers) → legacy `OPENAI_API_KEY`. Default model for the
  provider is `claude-haiku-4-5` (`--model` / `OKFSMITH_MODEL` override).
  A custom `--api-base` with the anthropic provider is treated as the
  Messages API host (`/v1/messages` is appended; the OpenAI-compat
  bare-host `/v1` rule does not apply). Covered by
  `tests/test_llm_anthropic.py` (32 tests); the dashboard provider list
  labels it "Native Anthropic Messages API".

## [0.6.1] - 2026-10-01

### Fixed
- **CI audit gate red: dependency security floors.** The `pip-audit` step in
  CI failed on published advisories: `fastmcp` 2.13.0.2 (PYSEC-2026-2474,
  PYSEC-2026-2475, PYSEC-2026-2476, GHSA-rcfx-77hg-w2wv) and `starlette`
  0.50.x (PYSEC-2026-161, PYSEC-2026-248, PYSEC-2026-249, PYSEC-2026-2280,
  PYSEC-2026-2281). Root cause: the old `uvicorn<0.32` cap forced pip to
  resolve the vulnerable fastmcp 2.13.0.2 (fastmcp>=3.2 needs
  `uvicorn>=0.35`), and `fastapi<0.122` pinned the vulnerable starlette
  0.50.x. Floors raised: `fastapi>=0.122,<0.143` (pulls starlette>=1.x),
  `uvicorn>=0.35,<0.55`, `fastmcp>=3.2,<5` (mcp extra). The audit step now
  also upgrades pip itself before running pip-audit, so the runner's pip
  CVEs can't fail the gate.

## [0.6.0] - 2026-10-01

### Added
- **Similarity-based entity resolution in the extraction pipeline:** dedup
  (`_find_duplicate`) gains a third branch after exact normalized-title match
  and same-resource match — a Jaccard coefficient over stemmed title tokens
  (`title_similarity`, reusing the search module's tokenizer + stemmer),
  merging candidates at similarity ≥ 0.8 with deterministic id tie-breaking.
  This is the dependency-free, offline-safe stand-in for the embedding
  similarity the pipeline previously logged as a v1 TODO: no model downloads,
  no network, reproducible across processes. Exact-match precedence is
  unchanged; low-overlap titles (e.g. "Incremental Sync" vs
  "Incremental Sync Guide", 2/3) still stay separate. Covered by
  `tests/test_extract_similarity.py` (15 tests).

## [0.5.2] - 2026-09-29

### Fixed
- **Dashboard frontend missing from the PyPI wheel:** the 0.5.1 wheel shipped
  only the dashboard's Python files, so a pip-installed
  `okfsmith dashboard` showed the "frontend bundle has not been built yet"
  placeholder instead of the SPA. `[tool.setuptools.package-data]` now
  includes `okfsmith/dashboard/static/*` in wheels and sdists, with
  regression tests (`tests/test_packaging.py`) guarding every runtime data
  directory against the same mistake.
- **Stale `test_version`:** `tests/test_core_smoke.py::test_version`
  hardcoded `"0.3.2"` and failed on every release since; it now compares
  `okfsmith.__version__` against the version declared in `pyproject.toml`.

## [0.5.1] - 2026-09-28

### Fixed
- **Knowledge-graph edge resolution for section concepts:** when a document
  is split into per-section concepts (id `doc/section`), markdown links in
  those concepts are relative to the source *document*, but the resolver
  treated the id as a file path — so `guide/related` linking `other.md`
  produced a dead `guide/other` edge (hidden entirely by the dashboard
  API) instead of linking the `other` document's primary concept. Links
  now resolve to the target document's primary section concept; genuinely
  broken links are still marked dead, and closer-scope nested ids still
  win. Found during demo testing of the v0.5.0 dashboard.

## [0.5.0] - 2026-09-28

### Added
- **Web dashboard (`okfsmith dashboard`):** a local-first web UI covering
  all ten product areas — Overview, Ingest (drag-and-drop with live
  parse → chunk → embed → validate → index progress), Explore
  (interactive knowledge graph), Temporal, Chat (grounded, with clickable
  citations), Validate, MCP, Eval, Doctor, and Settings. Binds only to
  `127.0.0.1`, per-launch token auth, default port 8931 with free-port
  fallback, fully offline packaged assets (no CDN). The knowledge graph
  renders ECharts-style: solid cluster-colored circles with labels
  inside, degree-scaled hubs, edge-to-edge arrows, and a cluster legend.
  See the [Web dashboard guide](https://bilal-junaid-jiwani.github.io/okfsmith/dashboard.html).

## [0.4.1] - 2026-09-28

### Fixed
- **Runtime `__version__` mismatch:** `okfsmith --version` and the chat
  startup banner reported `0.3.2` because `src/okfsmith/__init__.py` was
  never bumped in the v0.4.0 release commit (only `pyproject.toml` was).
  Now `__version__ = "0.4.1"` everywhere; single source of truth kept in
  sync by the release checklist.


### Added
- **`okfsmith eval` (P4):** golden-set evaluation harness — the RAG Triad
  (context relevancy, faithfulness, answer relevancy) per question, not just
  averages. Golden Q&A sets live at `<bundle>/eval/golden.json`
  (`{id, question, expected_answer, must_cite, tags}`; `okfsmith eval BUNDLE
  --init-sample` writes a starter set from the bundle's own concepts;
  malformed files fail as `error [golden-invalid]` / `error [golden-schema]`,
  never a traceback). Retrieval reuses the shared BM25 engine (same ranking
  as `search`/chat/MCP, including temporal supersession hiding with
  `--as-of` and `--include-superseded`). Keyless `--no-llm` heuristic scoring
  works end-to-end; with an LLM backend configured, the judge generates
  answers and scores metrics as `llm-judge`, degrading per-metric to
  heuristics on failure — every score is method-labeled, never presented as
  LLM-judged when it isn't. Per-question table with pass/fail vs thresholds
  (defaults 0.6 / 0.6 / 0.4, `--metric-threshold` overrides all) plus the
  actionable retrieval-vs-generation diagnosis for every failure (a golden
  `must_cite` concept not retrieved → retrieval; retrieved but answer wrong
  → generation). `--fail-under <0-100>` gates CI (exit 0 pass, exit 1 below);
  `--format json` emits the full machine-readable report. Sample golden set
  shipped at `examples/bundles/okf-primer/eval/golden.json`; new docs page
  `docs/eval.html`; CLI reference, README, SITEMAP, and man page updated.
- **`okfsmith eval` golden-set sanity warnings:** every question now gets a
  non-gating reference-support check — when a non-empty `expected_answer`
  shares almost no vocabulary with the retrieved context, the question
  carries a `warnings` entry (rendered as `!` lines in CLI output and in the
  JSON report) asking a human to verify the golden record. The gate still
  measures bundle quality only; a deliberately salted fabrication can evade
  this keyless check (documented in `docs/eval.html`).
- **MCP governed write-back:** four new tools on the MCP server —
  `preview_write_concept` (side-effect-free dry run showing the exact id,
  file path, frontmatter with provenance block, and serialized content),
  `write_concept` (create), `update_concept` (patch title/body/sources/links,
  with `dry_run` diff previews), and `audit_log` (reads the append-only
  `<bundle>/.okfsmith/audit.jsonl`). Writes are atomic (temp file +
  same-filesystem claim — creates let exactly one concurrent writer win via
  an atomic link, updates rename over the old file),
  always land at the `unverified` trust tier (any `verified` markers in
  input are stripped), stamp a `provenance` history entry in frontmatter
  (actor `mcp:<tool>`, UTC timestamp, input sources), are gated on the
  bundle validator (new errors ⇒ refused and rolled back; validator failure
  fails closed), never overwrite an existing concept (collisions return a
  structured error suggesting `update_concept`), and refuse to alter
  human-reviewed concepts without explicit `downgrade_trust=true` (the
  downgrade removes the `verified` marker and is recorded in provenance).
- **Temporal model (P2):** time-aware retrieval over `valid_from` /
  `valid_until` / `supersedes` / `last_verified` frontmatter. Retrieval
  groups hits by currency — validity window, then supersession, then trust
  tier, then `last_verified` recency (BM25 score orders hits within a
  group; trust and recency are tie-breakers; recency alone never demotes a
  human-reviewed concept below an unverified one). Concepts outside their
  validity window are demoted but still shown (marked `expired` / `future`);
  superseded concepts are hidden by default (shown last with
  `--include-superseded`, marked `superseded→<id>`) and never deleted.
  New CLI surface: `okfsmith search --as-of <ISO-8601 date|datetime>`
  replays validity and supersession chains at that instant;
  `--include-superseded` reveals hidden predecessors. `list` gains a
  `Valid` column (`—` for concepts with no temporal fields) and JSON
  `temporal_status`; `read` appends a one-line `[temporal: …]` badge for
  temporal/superseded concepts (plain current concepts print byte-identical
  output) and JSON `temporal_status`; `search` JSON always reports `as_of`
  and `superseded_hidden`. `validate` gains advisory warnings W016–W020
  (malformed temporal fields, `valid_until` before `valid_from`, dangling
  `supersedes` references, supersession cycles, future `last_verified`);
  warnings never affect conformance. `sync` carries temporal frontmatter
  over onto re-ingested concepts that keep the same ids (source values
  win); renamed/restructured concepts start fresh, and `sync` never
  auto-stamps `supersedes`. Malformed temporal frontmatter is untrusted
  input: it degrades to validator warnings, never tracebacks or eval/path
  use; `supersedes` lists are capped at 100 entries. The shared BM25
  engine applies the same ranking to CLI, chat, and MCP. New docs page
  `docs/temporality.html`; validation/CLI/syncing/searching docs, README,
  SITEMAP, and man page updated.
- `okfsmith sync BUNDLE SOURCE...`: incremental synchronization (P1).
  Each source file is SHA-256 fingerprinted and diffed against
  `<bundle>/.okfsmith/sync-state.json`; only new, changed, renamed, or
  deleted files are processed. `added` ingests (same LLM / `--no-llm`
  path as `ingest`); `updated` re-ingests and *replaces* the old
  concepts under the same ids (never `name-2` duplicates);
  `renamed` (identical content hash at a new path) keeps concept ids
  and history, rewriting only the `resource` provenance; `removed`
  deletes the file's concepts. Additions are applied before
  deletions. State writes are atomic (temp-file + rename) and resumable:
  an interrupted run leaves `incomplete: true` and the next run adopts
  already-ingested concepts instead of duplicating them. Safety rules:
  pre-flight on updates (a changed file whose new content would not
  ingest keeps its old concepts — reported `skipped`, never wiped),
  shared identical content is reference-counted, deletions are scoped
  to the sources passed in the current run, concept deletion is
  confined to the bundle root, and unreadable files become per-file
  `failed` rows instead of aborting the run. Modes: one-shot by
  default (`--poll` makes it explicit), `--watch` re-scans on a timer
  (`--interval` seconds, default 5; Ctrl-C stops cleanly),
  `--dry-run` previews without writing, `--format text|json` (stable
  JSON shape: `bundle`, `sources`, `dry_run`, `resumed`, `summary`,
  `files`; errors also come back as JSON error objects). New modules:
  `okfsmith.core.sync` (state, `plan_sync`, concept helpers),
  `okfsmith.cli.sync` (engine + rendering + watch loop);
  `Bundle.delete_concept()` (path-confined) and
  `dedup.unrecord_digest()` (stale manifest cleanup on replace/delete).
  39 new tests in `tests/test_sync.py`. Guides: `docs/src/syncing.md`
  (new docs-site page), `docs/commands.md`, `docs/src/cli.md`, man
  page, README CLI table. This addresses deferred item M1 (re-ingest
  pruning) for the sync path — see below.
- `okfsmith search BUNDLE QUERY`: BM25 full-text search over a bundle,
  stdlib-only (no new dependencies). Query syntax: bare terms, quoted
  phrases (`"knowledge graph"`), exclusions (`-deprecated`); an
  unbalanced quote is treated as a phrase, never an error. Tokenizer
  lowercases, splits on non-alphanumeric runs, drops ~40 English
  stopwords, and applies a small deterministic suffix stemmer
  (`sses→ss`, `ies→i`, `ing`/`ed`/`s` with length guards), so `running`
  matches `run`. Field weights: concept id/title ×3, description/tags
  ×2, body ×1; BM25 with k1=1.2, b=0.75; scores sort descending, ties
  broken by concept id for deterministic ordering. Flags: `--limit`/`-n`
  (default 10, must be ≥1), `--format text|json`, `--tier`, `--type`
  (same semantics as `list`). Text output is a rich table
  `Score | ID | Type | Title | Tier` (IDs never truncated) plus an
  `N result(s)` line; zero results exits 0 with `0 result(s)` and a
  stderr hint. JSON shape: `{"query", "results":
  [{"id","type","title","tier","score"}], "count"}`. Empty query is a
  usage error (exit 2); all failures print `error [CODE]:` + hint, never
  a traceback. The MCP server's `search` tool and the chat REPL's
  `/search` use the same engine, so CLI/MCP/chat results rank
  identically; `rank_concepts` is kept as a deprecated thin shim.
  No persistent on-disk index in v1 (built in memory per invocation;
  once at MCP startup). Guide: `docs/searching.md`.
- Docs: new `docs/searching.md` user guide (query syntax, tokenization,
  field weights, JSON shape, CLI/MCP/chat parity); README CLI table now
  lists `search`, documents `list --type`, and shows the correct
  `okfsmith chat v0.3.0` banner.

### Fixed
- **Adversarial QA, final pass — MCP concurrent-create race (HIGH):**
  simultaneous `write_concept` calls for the same slug could all report
  success — the check-then-write (`exists()` → `os.replace`) let N threads
  pass the existence check before any rename, so losers silently clobbered
  the winner while each appended an audit entry. Creates now claim the
  destination atomically with `os.link` (same-directory temp file, so the
  link is same-filesystem): exactly one writer wins, the rest get
  `Error: … already exists` with an `update_concept` hint, and no audit
  entry is written for refused duplicates. Updates (`overwrite=True`) still
  use `os.replace` — last-writer-wins is correct there and fully audited.
- **Adversarial QA, final pass — sync dedup-shared update (HIGH):** when an
  updated file dedup-skipped against a donor's identical content, the state
  entry kept the OLD digest and the old concepts' ids (the donor fallback
  only applied when no stale ids were found). Deleting the donor then
  orphaned live content: the bundle silently lost concepts the source file
  still contained. A dedup-shared update now always records the new digest
  and the donor's concept ids (shared ownership), so deleting the donor
  keeps the shared concepts and the next sync is a clean no-op.
- **Adversarial QA, final pass — temporal chain resolution (HIGH):**
  `SupersessionIndex.resolve_head` enumerated all simple paths with no
  memoization — exponential blowup on branching DAGs from frontmatter (32
  concepts: `list` 18.7s, `search` 17.7s; 40 nodes ≈ minutes). It is now a
  memoized dynamic program over `(concept, at)`: O(V+E) per retrieval pass,
  exact on acyclic graphs (differential-tested against the old algorithm on
  hundreds of random DAGs), deterministic and terminating on cyclic input
  (the depth cap it replaces is gone; over-long chains now resolve to the
  true head). The 32-node hostile bundle lists in ~0.2s.
- **Adversarial QA, final pass — symlinked sync source (MEDIUM):** syncing
  through a symlinked source root printed "skipped: source is a symlink"
  and then deleted every concept synced from the real directory (the
  resolved path still scoped the deletions). A refused source root is now
  excluded from deletion scoping — the bundle is untouched; real-directory
  syncs still detect deletions normally.
- **Adversarial QA, final pass — watch-mode staleness (LOW):** the
  mtime+size fast path is blind to a same-size edit with a preserved
  mtime. Watch mode now runs a full re-hash pass every 5 minutes
  (`_WATCH_FULL_VERIFY_INTERVAL`), bounding how long such a change can go
  unnoticed; the limitation is documented in the `--watch` help text.
- **Adversarial QA, final pass — eval threshold types (LOW):**
  `run_eval()` with a wrongly-typed `metric_threshold` (`"0.9"`, `[0.9]`,
  `{"context_relevancy": "high"}`, `True`) or `fail_under` (`"50"`, `nan`)
  leaked a raw `TypeError`; all such inputs now raise
  `EvalError("bad-threshold")` (the CLI already rejected them with exit 2).
- **Adversarial QA, final pass — eval golden-set sanity (MEDIUM):** the
  golden `expected_answer` was never compared against the bundle — a
  fabricated reference answer passed the gate with full confidence. Every
  question now gets a non-gating reference-support check: when a non-empty
  `expected_answer` shares almost no vocabulary with the retrieved
  context, the question carries a `warnings` entry (CLI `!` lines + JSON
  report field) asking a human to verify the golden record. The limitation
  (a deliberately salted fabrication can evade the keyless check) is
  documented in `docs/eval.html`.
- **Adversarial QA, final pass — MCP write-back (1 MEDIUM, 4 LOW):**
  `_reload_bundle` now evicts in-memory phantom concepts backed by
  `.preview-*.md` validation temps (a concurrent preview's temp file could
  previously be served by `get`/`list`); `update_concept` no-op detection
  is whitespace-normalized (a semantically identical body patch on the
  conventional blank-line-after-frontmatter form no longer rewrites the
  file or spams audit/provenance); `preview_write_concept` only prunes
  directories it created itself (pre-existing empty dirs survive);
  `sources`/`links` deeper than 32 levels, cyclic, over 10k nested items,
  or over 1M chars are refused with a clean error (previously
  `RecursionError` or multi-MB files + validator CPU burn); the recursive
  sanitizers are depth-limited and cycle-safe as defense in depth; a
  symlinked `.okfsmith/` directory now fails writes closed (rolled back,
  nothing audited outside the bundle).
- **MCP expansion (reviewer-1, 10 findings on the P6 MCP expansion):**
  continuation-token paging is now computed over result *items* only —
  notes and `##` section headers no longer consume the `max_chunks`
  budget, "N more" counts remaining items, and follow-on pages rebuild
  page 1 with the same unit-only budget, so paged output round-trips to
  exactly the unpaged item output (previously page 1 was built over
  notes+items while later pages used items only, silently dropping hits
  whenever notes were present); out-of-range tokens return a clean
  `Error: … out of range` instead of a bare "(continued)" header; the
  invalid-token error no longer claims a token could be "from another
  query" — tokens are opaque result-offset cursors; `max_tokens=0` now
  emits no item content (with the truncation marker and no
  un-progressable token) while negative/unparseable values are
  documented and treated as unbounded; `sync-state.json` source paths are
  treated as untrusted manifest entries in `diff` and `provenance` —
  only bundle-contained, non-symlink paths are hashed and displayed
  (bundle-relative, never absolute), outside paths, `..` escapes, and
  symlinks are skipped with an `untrusted manifest` marker instead of
  leaking host file digests/paths; `provenance` ingested records moved
  to their own section, appear exactly once (not under every
  `sources[]` entry), and are visible even when `sources[]` is absent;
  sync-state diff removed-entries render id plus an honest
  title/sha-unavailable detail instead of a bare id; `diff(against=…)`
  pre-scans with a 5000-file cap and rejects non-bundle directories
  before loading, so it can no longer walk `/` for seconds before
  failing; the `search` docs row now describes BM25 ranking (title
  highest, body lowest).
Fixed in this cycle from the pre-release QA audit (full details in the
QA bug report); criticals and highs listed, mediums/lows summarized.
- **Sync hardening (reviewer-1, 10 findings on `okfsmith sync`):**
  symlinked sources are now skipped with a per-file warning row instead of
  ingesting outside content (resolved-outside paths can never enter the
  sync state); an updated file's state entry records only the concepts its
  own new content produced, so deleting the last sharer of identical
  content deletes the stale concepts (per-concept owner lists via
  `core.sync.concept_owners`); the dedup-manifest digest record is kept
  while any other state entry still references the digest; files under the
  bundle directory are excluded from source scanning (with a note), so a
  bundle inside the synced tree can no longer self-ingest; the sync state
  refuses to write through a symlinked `<bundle>/.okfsmith/`
  (`error [sync-refused]`, audit-C1 pattern); non-UTF-8 filenames now
  round-trip through the state file reversibly (no more phantom renames —
  second sync reports 0 changes); concurrent syncs serialize on
  `<bundle>/.okfsmith/sync.lock` (`O_CREAT|O_EXCL`, stale locks reclaimed,
  loser exits with clean `error [sync-locked]`); watch-mode
  `--format json` is now JSONL (one compact object per line per cycle),
  documented in `--help` and `docs/src/syncing.md`; sources that can never
  succeed without user action (e.g. `.docx` without the `office` extra)
  are recorded as permanent per-source failures and reported every run
  without setting the `incomplete` flag (no more resume nag);
  `docs/src/syncing.md` safety wording updated to the actual symlink
  behavior. 18 new regression tests in `tests/test_sync.py`.
- **Critical (10):** symlink escapes confined to the bundle root in
  `ensure_index`/`append_log` (C1); concept ids `index`/`log` no longer
  overwrite the reserved files (C2); same-stem files in different
  directories no longer silently overwrite each other on ingest (C3);
  non-mapping/invalid-YAML frontmatter is preserved, not silently
  discarded on load+resave (C4); UTF-16 sources no longer ingest as
  NUL-garbage concepts (C5); validator no longer follows symlinked
  `.md` files or blesses escaping links (C6); slug collisions no longer
  silently overwrite concepts (C7); non-UTF-8 `.md` now yields
  `error [unreadable-file]` naming the file instead of a
  `UnicodeDecodeError` traceback in `read`/`validate`/`list`/`graph`/
  `chat` (C8); impossible YAML dates report E001 instead of crashing
  with `ValueError` (C9); scalar `verified`/`tags` frontmatter
  (e.g. `verified: yes`) no longer crash MCP tools and CLI trust paths
  with `TypeError` (C10).
- **High (17):** unreadable directory-discovered files report a per-file
  "failed" row instead of aborting the batch with `PermissionError`
  (H1); concurrent ingests no longer lose index entries (H2);
  quadratic link regexes hardened against crafted-input DoS (H3); deep
  YAML nesting is caught instead of crashing with `RecursionError`
  (H4); text-only Notion exports (no `_files/` dir) are recognized
  (H5); nested ZIPs are parsed to documented depth 1 instead of being
  silently skipped (H6); `graph --output` no longer silently overwrites
  existing files (H7) and handles directory/missing-parent targets
  cleanly across formats (H8); `ingest` with a file path as the bundle
  emits `error [not-a-directory]` (H9); FIFO/non-file ingest sources
  get a clean error instead of `NotADirectoryError` (H10); `init` I/O
  failures surface `error [io-error]` (H11); directories named `*.md`
  no longer crash `list`/`read`/`validate` (H12); `read --format json`
  handles non-JSON-native frontmatter values (H13); null bytes in link
  targets no longer crash `graph` (H14); over-long titles are truncated
  to filesystem-safe lengths (H15); LLM transport failures retry instead
  of aborting the whole extraction run (H16); `Bundle.load` no longer
  hangs on a FIFO named `*.md` (H17).
- **Medium/low (30 + 25):** summary of the remaining audit fixes —
  BOM handling in titles/frontmatter (M9), latin-1 mojibake flagged not
  silently corrupted (M10), binary-file detection on ingest (M11),
  `--dry-run` dedup-manifest parity
  (M18), parse errors reported accurately instead of the stub-prevention
  message (M2), phantom `'---'` concepts from frontmatter'd sources
  (M3), non-UTF-8 filename log encoding (M8), `validate --strict` output
  matches its exit code (M7), titled-link W001/W002 false positives
  (M12), code-block/graph-vs-validator link disagreements (M13, L3),
  mermaid node-ID collisions (M15), `check()` no longer creates missing
  dirs (M16), chat `/model` typo no longer kills the REPL session
  (M25), `graph --format text` inflection and other low-severity
  polish (L1–L25); stale `--bundle` flag usage removed from the MCP
  README (M26).
- **okfsmith eval (reviewer-2, 4 findings on the P4 eval harness):** a golden
  `must_cite` concept that retrieval never surfaced now fails its question
  with a `retrieval` diagnosis (previously it silently passed whenever the
  metric scores cleared their thresholds); the run's judge mode is derived
  from the per-score method labels alone — a configured LLM judge whose
  every call fails reports `heuristic`, and `mixed` is reserved for
  genuinely mixed runs (the text header wording updated to match);
  `--init-sample` starter questions are now self-consistent (phrased from
  the concept's own vocabulary instead of `What is {title}?`, whose
  question-word the keyless answer-relevancy heuristic could never cover),
  so the starter set passes `eval --no-llm` on a healthy bundle; removed
  the dead duplicate `eval` command — the old spec-YAML design whose
  `from okfsmith.cli.eval import ...` never resolved — leaving only the P4
  `eval`.

### Deferred (deliberate, pending design decisions)
- Re-ingest pruning / ghost-concept cleanup (M1): superseded for the
  `sync` path — `okfsmith sync` now replaces concepts on update and
  deletes concepts for removed sources (see Added above). Plain
  `ingest` still creates `-2`, `-3`, … suffixed versions on re-ingest
  by design (the C3 no-silent-overwrite rule); use `sync` when sources
  change in place.
- Validator line numbers (M29): cosmetic; `Finding` carries no line
  field by design.
- Byte-identical ingest output (L12): `generated.at` timestamps are
  inherently time-dependent; a frozen-time mechanism is needed.

## [0.3.2] — 2026-09-28

### Fixed
- PyPI project page was blank ("The author of this package has not provided
  a project description") on every release: the upload script only sent
  identity/digest fields, never the release metadata. It now sends the full
  metadata form fields (summary, long description, classifiers, dependencies,
  project URLs) parsed from the distribution's own PKG-INFO/METADATA,
  twine-style. README links/images now use absolute GitHub URLs so they
  render on PyPI.

## [0.3.0] — 2026-09-26

### Added
- "Any model, any API key": `--provider` presets for 15 OpenAI-compatible
  endpoints (`openrouter`, `groq`, `mistral`, `deepseek`, `together`,
  `fireworks`, `deepinfra`, `anyscale`, `perplexity`, `xai`, `gemini`,
  `openai`, `agentrouter`, `lmstudio`, `ollama`) on `okfsmith ingest` and
  `okfsmith chat`, plus `--api-base` for literally anything else (Azure
  OpenAI, self-hosted vLLM / llama.cpp, any compat proxy). Keys via
  `OKFSMITH_API_KEY` (env, preferred), `--api-key` (with a one-time
  shell-history warning), `AGENTROUTER_API_KEY` (honored when the provider
  is `agentrouter`), or legacy `OPENAI_API_KEY`; models via `--model` /
  `OKFSMITH_MODEL`. OpenRouter is the flagship — one key routes to hundreds
  of models via `vendor/model`-style IDs. `okfsmith doctor` now reports the resolved
  provider, base URL, model, and key status (`set (hidden)` / `not set`) —
  keys are never displayed, logged, or persisted. Unknown `--provider`
  names fail loudly with the valid list. Anthropic's native API is not
  OpenAI-compatible: it needs a compat proxy via `--api-base` (or the
  `openrouter` preset).
- `okfsmith chat BUNDLE`: interactive Claude Code / Gemini CLI style REPL over
  a bundle — natural-language questions answered with `[concept-id]` citations,
  multi-turn follow-ups resolved against recent context, slash commands
  (`/help`, `/ingest`, `/list`, `/read`, `/search`, `/validate`, `/graph`,
  `/doctor`, `/model`, `/clear`, `/exit`), persistent line history at
  `~/.okfsmith/history`. Generative answers via Ollama (default) or
  `OPENAI_API_KEY`; falls back to extractive mode when no LLM is reachable
  (`--no-llm` forces it). Hallucinated citations are stripped — every cited
  concept is a real bundle concept.
- `rank_concepts()` in `okfsmith.mcp_server.server`: shared retrieval ranking
  used by both the MCP `search` tool and the chat REPL.
- **MCP server expansion (P6):** three new read-only tools — `traverse`
  (breadth-first neighborhood expansion over markdown links: depth capped at
  3, cycle-safe visited set, optional `relation_filter` matched against link
  text or target id, currency-aware ordering with superseded concepts hidden
  by default), `provenance` (claim → source chain: `sources[]` frontmatter +
  footnote refs → the `sync-state.json` ingested-source manifest with source
  file and SHA-256 digest; never crashes on missing/malformed sources), and
  `diff` (bundle version diff: added/removed/changed concepts by id + title +
  body SHA-256, against another bundle directory via `against=` or against
  the `sync-state.json` snapshot). Evidence budgets on all eight tools:
  `max_chunks` (per-response item cap, default 10 for `search`/`traverse` and
  50 elsewhere, hard cap 50), `max_tokens` (approximate output budget,
  truncates at whole-item boundaries with a `…[truncated, N more]` marker),
  and `continuation_token` (opaque paging token; invalid tokens return a
  clean error, never a traceback). `search` gains `include_superseded` to
  reveal hidden predecessors. All existing tool signatures are backward
  compatible and default outputs are byte-identical. Docs (`docs/src/mcp.md`)
  updated.

### Changed
- `okfsmith chat` startup UI redesigned in the Qwen Code / Claude Code /
  Antigravity CLI aesthetic: giant gradient (yellow→orange→magenta) ASCII
  `OKFSMITH` logo, dimmed `okfsmith chat vX.Y.Z` line, Antigravity-style
  `Bundle: <name> (<N> concepts) · <provider> · <model>` info line,
  Qwen-style "Tips for getting started:" list, colored bundle-aware prompt
  (`kb ›`), and a subtle `✦` marker before answers. Piped / `NO_COLOR`
  output stays plain ASCII with zero escape codes. The banner no longer
  shows LLM key status (still in `/model` and `doctor`, masked).
- Documentation website: new static docs site in `docs/` (13 pages +
  `index.html`), styled after the Claude Code docs — warm dark theme, sticky
  topbar with search (Ctrl/Cmd+K), six-tab section bar, grouped sidebar nav,
  sticky "On this page" TOC, per-code-block and per-page copy buttons.
  Built by `python3 docs/build.py` (no npm, no build step); deploys as-is
  from GitHub Pages with `/docs` as the source folder. Includes
  `sitemap.xml`, `robots.txt`, `llms.txt`, JSON-LD metadata, `404.html`,
  and client-side search over a generated index.

## [0.2.0] — 2026-09-26

### Added
- Positional bundle argument across all commands (`okfsmith ingest BUNDLE SOURCE...`)
- `okfsmith doctor` environment check (dependencies, extras, Ollama, writability)
- JSON output modes for `list` and `read`; `validate --format json` now reports top-level `status`, `concepts`, `error_count`, `warning_count`
- `ingest` flags: multiple sources, `--recursive`, `--dry-run`, `--quiet`, TTY progress
- `init --force` confirmation (bypass with `--yes`)
- Constrained `--format` / `--tier` / `--transport` choices (exit 2 on misuse)
- Stable CLI error codes (`error [CODE]:` + hint, no tracebacks); JSON error objects for JSON commands
- Interactive graph viewer upgrades: `#empty[hidden]` fix, Okabe–Ito colorblind-safe palette, trust-by-shape legend, keyboard access, Esc handling, screen-reader concept list, backlinks in detail panel, minimal-markdown rendering, reset view, match count, neighborhood emphasis, loading/error states
- Rich-markup escaping for all dynamic CLI table content
- Security regression test suite (`tests/test_security.py`)
- Docs: install/quickstart/commands/pipeline/parsing/llm/validation/mcp/skill/troubleshooting/faq guides, `llms.txt`

### Changed
- MarkItDown moved to the optional `office` extra (leaner default install)
- Dependency bounds tightened (typer, pyyaml, rich, httpx, liteparse, fastmcp, docling, pytest)
- PyPI metadata: description, keywords, classifiers, project URLs

### Security
- markitdown floor `>=0.1.5` (CVE-2025-11849 mammoth arbitrary file read; CVE-2025-64512 pdfminer.six RCE)
- Link targets contained inside the bundle root (escaping links become dead links)
- ZipSlip-safe extraction with member-count and total-size caps
- `Bundle.load` skips symlinked concepts and reserved files
- Subdir traversal rejected in index/log helpers
- Human-review errors no longer disclose absolute bundle paths
- Viz `safeHref`: strip leading C0 controls before scheme check (blocks `\x01javascript:` bypass); behavioral node regression test
- Viz `md()`: `javascript:`/`data:`/`vbscript:`/protocol-relative URLs never become anchors

### Fixed
- Sub-1000-char ingest reports `skipped (below 1000-char minimum; stub prevention)` instead of hollow `ok`; digest not recorded; `--dry-run` parity
- `okfsmith mcp` without the `mcp` extra emits `error [missing-extra]` + hint (no traceback)
- `init` on a file path emits `error [not-a-directory]` (no traceback)
- `graph --output` works for json/mermaid/text (was silently ignored); graph JSON includes `dead_links`
- `list` IDs never truncate (copy-paste safe); empty `list` shows next-step hint
- `ruff check src/ tests/` fully clean; CI workflow fixed (master trigger, cross-platform smoke, honest PyMuPDF check)
- Docs: trust derived from `verified` (not a literal `trust:` field); embedding similarity labeled v1 TODO; Notion CSV = one document each; canonical spec URLs in examples

## [0.1.0] — 2026-09-26

Initial public release: init/ingest/validate/list/graph CLI, OKF §11
validator, offline HTML graph viewer, MCP server, `okfsmith-build` skill pack.
