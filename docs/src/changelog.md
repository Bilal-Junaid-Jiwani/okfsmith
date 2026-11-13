---
title: Changelog
eyebrow: Troubleshooting
description: Release history for okfsmith — what changed in each version, what's coming next, and upgrade notes. Follows Keep a Changelog and Semantic Versioning.
---

## [0.27.0] — 2026-11-13 {#v0-27-0}

### Added {#v0-27-0-added}

- **Viz HTML graph shows temporal status** — the interactive viewer
  (`okfsmith graph --format html`) is the last surface to carry the
  temporal status the other surfaces already show. Nodes carry
  `temporal_status` and `superseded_by`; non-current nodes are struck
  through on the canvas (a shape channel, never color alone), get a
  temporal badge in the detail panel, are counted in the header
  stats, and are named in the screen-reader concept list. Plain
  bundles show no non-current count and no strike-through legend row.

## [0.26.0] — 2026-11-12 {#v0-26-0}

### Added {#v0-26-0-added}

- **Graph nodes show temporal status** — `okfsmith graph` now carries
  the same temporal status the `search` / `list` / `read` surfaces
  (and the dashboard graph API) already show. JSON nodes carry
  `temporal_status` and `superseded_by`; the text report lists
  non-current concepts; Mermaid labels mark them. Plain bundles print
  byte-identical output to before.

## [0.25.2] — 2026-11-11 {#v0-25-2}

### Fixed {#v0-25-2-fixed}

- **Docs-changelog checker tests failed on macOS/Windows** — the tmp
  fixtures used `CHANGELOG.md` and `changelog.md`, which are the same
  file on case-insensitive filesystems. Fixtures now use distinct
  basenames (`root-changelog.md` / `docs-changelog.md`).

## [0.25.1] — 2026-11-11 {#v0-25-1}

### Fixed {#v0-25-1-fixed}

- **Docs changelog backfill** — the docs changelog listed only 9 of
  the 55 released versions, jumping from 0.25.0 straight to 0.7.1.
  All 56 versions (55 released + docs-only 0.4.0) are now present.

### Added {#v0-25-1-added}

- **CI check that the docs changelog stays complete** — a new
  `scripts/check_docs_changelog.py` fails the build if any version
  in root `CHANGELOG.md` is missing from `docs/src/changelog.md`.

## [0.25.0] — 2026-11-10 {#v0-25-0}

### Added {#v0-25-0-added}

- **MCP `search` hits and `list` rows show temporal status** — a
  non-current row now reads `_(superseded by `<id>`)_`,
  `_(expired)_`, or `_(not yet valid)_`, evaluated at the `as_of`
  replay instant when one is given. Previously a superseded
  concept revealed with `include_superseded=True`, or listed
  outright, read exactly like a current one.

## [0.24.0] — 2026-11-09 {#v0-24-0}

### Added {#v0-24-0-added}

- **Graph nodes show temporal status:** `GET /api/v1/bundles/{id}/graph`
  now returns the same explicit `temporal_status` and `superseded_by`
  per node that the concepts listing, the concept detail endpoint, and
  the `/search` hits already carry, evaluated at now through the shared
  supersession index — and the dashboard graph canvas rings a
  non-current node (superseded, expired, or not yet valid) with a dashed
  outline, explained by a "not current" legend entry.

## [0.23.0] — 2026-11-08 {#v0-23-0}

### Added {#v0-23-0-added}

- **Concepts listing rows show temporal status:** `GET
  /api/v1/bundles/{id}/concepts` now returns the same explicit
  `temporal_status` and `superseded_by` per item that the `/search` hits
  and the concept detail endpoint already carry, evaluated at now
  through the shared supersession index — and the dashboard chat's
  `/search` and `/list` slash commands pass both fields through to their
  citation chips.

## [0.22.0] — 2026-11-07 {#v0-22-0}

### Added {#v0-22-0-added}

- **Chat citation chips show their concept's sources:** `GET
  /api/v1/search` now returns the same explicit `sources` list per hit
  that the concepts listing, the concept detail endpoint, and the chat
  message citations already carry, and the dashboard chat's `/search`
  and `/list` slash commands pass it through to their citation chips
  instead of building them with a hardcoded `sources: []`.

## [0.21.0] — 2026-11-06 {#v0-21-0}

### Added {#v0-21-0-added}

- **Dashboard concept detail views show temporal status:** `GET
  /api/v1/bundles/{id}/concepts/{concept_id}` now returns the same
  explicit `temporal_status` and `superseded_by` fields the `/search`
  hits already carry, evaluated at now through the shared supersession
  index — and both detail views (the Explore graph's detail panel and
  the concept modal opened from a search hit) pill it in the meta row.

## [0.20.1] — 2026-11-05 {#v0-20-1}

### Fixed {#v0-20-1-fixed}

- **Man page version pin missed in 0.20.0:** the 0.20.0 release bumped
  `pyproject.toml` and the project website but not `man/okfsmith.1`, so
  `test_man_page_states_current_version` failed and CI went red on the
  release commit (the man page also ships in the sdist, so the published
  0.20.0 sdist carried the stale header).

## [0.20.0] — 2026-11-05 {#v0-20-0}

### Added {#v0-20-0-added}

- **Dashboard Explore search gains an "Include superseded" toggle:**
  `GET /api/v1/search` has hidden superseded matches by default since
  the temporal replay landed, reporting them only as a
  `superseded_hidden` count — but the Explore page neither passed the
  API's `?include_superseded=` flag nor read that count, so a search
  whose only matches were superseded looked like it matched nothing, and
  those matches were unreachable from the dashboard without the CLI or
  chat.

## [0.19.0] — 2026-11-04 {#v0-19-0}

### Added {#v0-19-0-added}

- **Dashboard concept detail views show trust tier and type:** `GET
  /api/v1/bundles/{id}/concepts/{concept_id}` now returns the same
  explicit `trust_tier` and `type` fields the listing and `/search`
  responses already carry, and both detail views — the Explore graph's
  detail panel and the concept modal opened from a search hit — pill the
  real trust tier (`human-reviewed` green, `machine-confirmed` amber,
  `unverified` muted) and show the type next to it.

## [0.18.0] — 2026-11-03 {#v0-18-0}

### Added {#v0-18-0-added}

- **Dashboard Explore search gains type and trust-tier filters:** `GET
  /api/v1/search` has accepted `?type=` / `?trust_tier=` since 0.14 (the
  dashboard analogue of `okfsmith search --type` / `--tier`), but the
  Explore page never exposed them, so narrowing a search meant
  re-running it on the CLI or in chat.

## [0.17.1] — 2026-11-02 {#v0-17-1}

### Fixed {#v0-17-1-fixed}

- **Dashboard Explore search hits showed an "unknown" trust pill:** the
  hit row rendered `tierPill(r.tier)`, but `GET /api/v1/search` never
  returns a `tier` field — its trust field is `trust_tier` (`tier` is
  the high/medium/low recency bucket the concept endpoints return).

## [0.17.0] — 2026-11-01 {#v0-17-0}

### Added {#v0-17-0-added}

- **Chat `/list` gains `--type` and `--tier` filters (inventory filter
  parity):** the chat listing was the only concept-inventory surface
  that could not narrow at all — `okfsmith list --type` / `--tier`, the
  MCP `list` tool's `filter_type` / `tier_filter`, and the dashboard
  listing's `?type=` / `?trust_tier=` already could — so browsing a
  large bundle from the REPL meant paging through everything.

## [0.16.0] — 2026-10-31 {#v0-16-0}

### Added {#v0-16-0-added}

- **MCP `list` tool gains a `tier_filter` parameter (inventory filter
  parity):** the MCP `list` tool was the only concept-inventory surface
  that could not narrow by trust tier — `okfsmith list --tier` and the
  dashboard listing's `?trust_tier=` already could, and the MCP `search`
  tool already had `tier_filter` — so an agent listing a bundle could
  not ask for just the human-reviewed (or just the unverified) concepts
  without fetching the whole inventory and filtering itself.

## [0.15.0] — 2026-10-30 {#v0-15-0}

### Added {#v0-15-0-added}

- **Dashboard concept listing gains type and trust-tier filters:** `GET
  /api/v1/bundles/{id}/concepts` was the only concept-inventory surface
  that could not narrow by frontmatter `type` or trust tier — `okfsmith
  list --type` / `--tier` and the MCP `list` tool's `filter_type`
  already could — and it did not even report those two fields, so a
  dashboard client could not show them without an extra call per
  concept.

### Fixed {#v0-15-0-fixed}

- **Project website dashboard caption no longer claims a version the
  screenshot does not show:** the caption under the dashboard screenshot
  said "The screenshot shows okfsmith v0.8.7", but the screenshot itself
  carries a v0.8.6 badge.

## [0.14.0] — 2026-10-29 {#v0-14-0}

### Added {#v0-14-0-added}

- **Dashboard search hits now carry type, trust tier, and temporal
  status:** `GET /api/v1/search` results previously returned only
  `bundle_id`, `concept_id`, `title`, `snippet`, and `score` — a
  dashboard client could not tell a current hit from a superseded,
  expired, or future one, or show its type/tier, without an extra call
  per hit, while `okfsmith search --format json` already reported all of
  it.

## [0.13.0] — 2026-10-28 {#v0-13-0}

### Added {#v0-13-0-added}

- **Chat REPL `/search` gains `--limit` / `-n` (limit parity):** the
  chat was the only one of the four search interfaces without a result
  cap — the CLI has `-n` / `--limit`, the MCP `search` tool has `limit`,
  and the dashboard search has `?limit=`, but chat hardcoded 10 results.

## [0.12.1] — 2026-10-27 {#v0-12-1}

### Fixed {#v0-12-1-fixed}

- **Man page and project website now state the current release:** the
  0.12.0 release bumped `pyproject.toml` but left `man/okfsmith.1`
  ("okfsmith 0.11.1") and `docs/site/index.html` ("Latest release
  v0.11.1") stale, which the `test_packaging.py` version pins caught as
  a CI failure on the 0.12.0 commit.

## [0.12.0] — 2026-10-27 {#v0-12-0}

### Added {#v0-12-0-added}

- **Type/tier filter parity across all four search interfaces:** the
  CLI's `search --type` / `--tier` flags (and their filter-before-limit
  semantics from 0.11.1) now exist everywhere else too — the MCP
  `search` tool gains `type_filter` / `tier_filter` parameters, the chat
  REPL's `/search` gains `--type` / `--tier` flags (either form,
  anywhere in the argument, like `--as-of`), and the dashboard `GET
  /api/v1/search` gains `?type=` / `?trust_tier=` query parameters.

## [0.11.1] — 2026-10-26 {#v0-11-1}

### Fixed {#v0-11-1-fixed}

- **`search --type` / `--tier` filters no longer lose matches below the
  `--limit` cut:** the filters used to apply *after* results were
  truncated to `--limit`, so `search ./kb refund --type guide -n 1`
  returned nothing when the only guide ranked second.

## [0.11.0] — 2026-10-25 {#v0-11-0}

### Added {#v0-11-0-added}

- **Chat REPL `/search` gains temporal replay (`--as-of`,
  `--include-superseded`):** the chat slash command now accepts the same
  temporal query flags as `okfsmith search --as-of` /
  `--include-superseded`, the MCP `search` tool's `as_of`, and the
  dashboard `GET /api/v1/search` — completing temporal-replay parity
  across all four search interfaces (the 0.10.0 notes claimed four-way
  parity, but chat's `/search` never actually accepted the flags).

## [0.10.0] — 2026-10-24 {#v0-10-0}

### Added {#v0-10-0-added}

- **Dashboard `GET /api/v1/search` gains `as_of` temporal replay and
  `include_superseded`:** the dashboard search endpoint now accepts the
  same temporal query parameters as `okfsmith search --as-of` /
  `--include-superseded` and the MCP `search` tool's `as_of` —
  completing temporal-replay parity across all four interfaces (CLI,
  chat, MCP, dashboard).

## [0.9.0] — 2026-10-23 {#v0-9-0}

### Added {#v0-9-0-added}

- **MCP `search` tool gains `as_of` temporal replay:** the MCP server's
  `search` tool now accepts an `as_of` parameter (ISO-8601 date or
  datetime) — the MCP analogue of the CLI's `--as-of` flag.

## [0.8.7] — 2026-10-22 {#v0-8-7}

### Fixed {#v0-8-7-fixed}

- **Dashboard `GET /api/v1/sync/sources` docstring drift:** the
  endpoint's contract docstring promised a `never` source status that
  the code never emits (only `ok`, `stale`, and `error` are possible).

### Added {#v0-8-7-added}

- **`tests/test_dashboard_sync_sources.py`:** status-contract coverage
  for `GET /api/v1/sync/sources` — previously only the empty-sources
  shape was asserted.

## [0.8.6] — 2026-10-21 {#v0-8-6}

### Fixed {#v0-8-6-fixed}

- **CI-only test fix (no runtime changes):**
  `test_cli_min_chars_requires_no_llm` asserted on the raw text of
  Typer's rich error panel; on CI the panel is color-styled (ANSI) and
  wrapped, so the exact phrase never matched and every matrix job went
  red for 0.8.5.

## [0.8.5] — 2026-10-21 {#v0-8-5}

Six fixes from an external hands-on review of the offline (`--no-llm`)
path — an independent tester installed the package and ran the pipeline
in a sandbox; every finding below was reproduced against the code before
being fixed.

### Fixed {#v0-8-5-fixed}

- **Offline concepts were stamped with a stale version:** `generated.by`
  on every `--no-llm` concept read `okfsmith/0.2.0` (a hardcoded literal
  in `parsers/ingest_no_llm.py`) regardless of the installed release.

- **PDFs now split into sections:** the PDF parser rebuilds page text
  from liteparse's font structure — lines set in a larger or bold font
  become ATX headings, so sectioning splits a multi-section PDF into one
  concept per section instead of a single document-wide concept.

- **Offline graph is no longer empty:** each `--no-llm` concept now ends
  with a `## See also` section linking its sibling sections of the same
  document — the previous/next section, plus any section whose title the
  section's text mentions.

- **Offline descriptions are section-specific:** the frontmatter
  `description` is derived from the section's own text (first meaningful
  sentence, trimmed) instead of one identical line — "Draft concept
  extracted without LLM; needs review" — on every concept.

### Added {#v0-8-5-added}

- **`--min-chars N` on `ingest` and `sync`:** the stub-prevention
  threshold (sources under ~1000 total characters produce no concepts)
  is now overridable.

- **`sources[]` in offline concepts:** `--no-llm` concepts now emit the
  same `sources[]` frontmatter the LLM pipeline produces — one entry
  citing the source document, page-pinned from the section's page span —
  plus `source_digest` with the source file's SHA-256 when the caller
  computed one (CLI ingest and the dashboard do).

### Tests {#v0-8-5-tests}

- New `tests/test_offline_review_fixes.py` (21 tests) pins all six
  fixes, including a multi-section styled-PDF fixture, `--min-chars`
  CLI/dry-run/sync behaviour, validator cleanliness of offline bundles
  (no W001/W005/W008/W015), and graph edges from offline links.

- `test_ingest_no_llm_draft_shape` updated for derived descriptions; the
  dashboard concepts-filter test now queries a body-only term (linked
  titles are body content and legitimately match).

## [0.8.4] — 2026-10-21 {#v0-8-4}

### Fixed {#v0-8-4-fixed}

- **Dashboard launch-token docs corrected:** the launch flow moved from
  a `?token=` query parameter to a `#token=` URL fragment (fragments are
  never sent to the server and never land on a browser's command line),
  but the module docstrings in `dashboard/server.py`,
  `cli/dashboard_cmd.py`, and `dashboard/auth.py` still described the
  old query-parameter flow.

### Added {#v0-8-4-added}

- **Auth-contract unit tests:** new `tests/test_dashboard_auth.py` (9
  tests) pins `TokenAuth.check` edge cases the HTTP tests don't reach —
  case-insensitive `Bearer` scheme, whitespace trimming, a failed
  `?token=` attempt not burning the single use, the query burn not
  breaking the bearer path, and the 401 response shape
  (`WWW-Authenticate: Bearer`).

## [0.8.3] — 2026-10-20 {#v0-8-3}

### Fixed {#v0-8-3-fixed}

- **Ingest embedding calls cut ~8x with `--embeddings`:** the
  embedding-similarity duplicate check re-embedded *every* existing
  concept's title+body for *every* new section (S sections × M existing
  concepts = S×M wasted embedding API calls).

## [0.8.2] — 2026-10-17 {#v0-8-2}

### Fixed {#v0-8-2-fixed}

- **CI fix (take 2):** the 0.8.1 fix for
  `test_ingest_embeddings_rejected_with_no_llm` (wide panel via
  `COLUMNS=200`) was not sufficient: when color is enabled — as on CI —
  typer's rich error panel highlights option names with ANSI styles
  *inside* the words (`--embeddings` renders as styled `-` +
  `-embeddings`), so the plain-text substring never matches.

## [0.8.1] — 2026-10-17 {#v0-8-1}

### Fixed {#v0-8-1-fixed}

- **CI fix:** `test_ingest_embeddings_rejected_with_no_llm` asserted on
  the `--embeddings`/`--no-llm` usage-error text, but rich wraps the
  error panel to the terminal width — on CI's narrow non-tty the message
  wrapped mid-phrase and the substring check failed on all 12 matrix
  jobs.

## [0.8.0] — 2026-10-17 {#v0-8-0}

### Added {#v0-8-0-added}

- **Opt-in embedding-similarity duplicate detection for ingest**
  (`okfsmith ingest --embeddings openai`, or `OKFSMITH_EMBEDDINGS`):
  after the existing exact-title, same-resource, and stemmed-token
  title-similarity checks, a new branch embeds each new concept's
  title+body via any OpenAI-compatible `/embeddings` endpoint and merges
  the best existing concept at cosine similarity ≥ 0.87 — catching
  paraphrases the offline checks miss ("How to sync your vault" vs
  "Vault synchronization guide").

- Docs: `docs/OVERVIEW.md` (Link step), `docs/commands.md` (ingest
  flags), and `docs/llm.md` (new "Embedding similarity" section)
  describe the feature truthfully; the old "v1 TODO, not yet
  implemented" note is gone.

## [0.7.15] — 2026-10-16 {#v0-7-15}

### Added {#v0-7-15-added}

Together with the existing suite, `core/sync.py` is now at 96% line
coverage and `dashboard/settings.py` at 100%.

- **Regression tests pinning the 0.7.13 security hardening:** the
  sync-lock module's concurrency safety invariants now have dedicated
  coverage in `tests/test_sync_lock_safety.py` (22 tests): a lock naming
  a live PID is never reclaimed no matter its age, a dead-PID lock is
  reclaimed only once older than 10 minutes, and the releaser removes
  the lock only when it still names our own PID.

- **`tests/test_dashboard_settings.py` (6 tests)** for the
  lock-protected `DashboardSettings` store:
  `update`/`get`/`snapshot`/`clear` contract, snapshot-copy isolation,
  concurrent-update safety, and — the audit invariant — `os.environ` is
  never mutated by settings overrides.

## [0.7.14] — 2026-10-15 {#v0-7-14}

### Fixed {#v0-7-14-fixed}

- **MCP server no longer serves a stale index until restart:** every
  read tool (`index`, `list`, `search`, `get`, `neighbors`, `traverse`,
  `provenance`, `diff`) now re-checks a cheap on-disk fingerprint (file
  path, size, mtime per `*.md`) before serving and reloads the bundle —
  rebuilding the supersession index — whenever a concept was added,
  edited, or deleted by the CLI or any other process after the server
  started.

## [0.7.13] — 2026-10-15 {#v0-7-13}

### Security {#v0-7-13-security}

This release fixes 10 findings from an independent security audit of the
0.7.12 codebase (trust-tier integrity, secrets handling, concurrency,
authentication, and input validation).

- **CRITICAL — `_inject_backlinks` no longer mutates `human-reviewed`
  concepts:** retroactive backlink injection now skips concepts whose
  trust tier is `human-reviewed`, so ingesting an untrusted document can
  no longer append LLM-generated text to a human-verified concept while
  its badge remains.

- **MCP server is read-only by default:** `okfsmith mcp` now registers
  only the 8 read tools unless `--allow-writes` is passed, and
  `downgrade_trust=true` from an agent is rejected unless
  `--allow-trust-downgrade` is given by the server operator.

- **Dashboard settings no longer mutate process-global `os.environ`:**
  `PUT /api/v1/settings` writes to a lock-protected in-memory store on
  `app.state`; background jobs receive an immutable config snapshot, so
  a settings change can no longer race a running ingest/sync/eval job.

- **`OPENAI_API_KEY` is now provider-scoped and cleartext HTTP is
  blocked:** the legacy key falls back only for `provider == "openai"`,
  and `OpenAICompatibleBackend` raises `LLMError` instead of sending an
  API key over non-loopback `http://`.

- **`sync.lock` never steals a live lock:** a lock naming a live PID is
  no longer treated as stale, whatever its age; reclamation now requires
  a dead (or unreadable) PID *and* age > 10 minutes.

- **MCP network transports require a token:** `--transport sse` /
  `streamable-http` now enforce a per-launch bearer token
  (`--auth-token` / `OKFSMITH_MCP_TOKEN` / auto-generated and printed
  once).

- **Dashboard bootstrap token moved to URL fragment:** the launch URL is
  now `#token=...` instead of `?token=...`, so the token no longer
  appears in the OS process table; the frontend sends it as an
  `Authorization` header.

- **Re-ingest stamps `supersedes`:** when plain `ingest` creates a
  `-2`/`-3` suffixed duplicate, the new concept's frontmatter records
  `supersedes: [<old id>]` so the temporal model demotes the stale
  version in search/RAG.

- **`eval/golden.json` size caps:** `load_golden_set()` now refuses
  files over 5 MiB (`golden-too-large`) and sets over 1,000 questions
  (`golden-too-many`).

- **History file permissions + single version source:** `~/.okfsmith` is
  `0o700` and the history file `0o600`; `__version__` now comes from
  `importlib.metadata` instead of a second hardcoded string.

## [0.7.12] — 2026-10-14 {#v0-7-12}

### Fixed {#v0-7-12-fixed}

- **Validator now honors the M28 frontmatter size guard like the bundle
  loader:** a frontmatter block larger than 20,000 lines or 1,000,000
  characters is treated as unparseable (E001) instead of being parsed
  normally.

## [0.7.11] — 2026-10-13 {#v0-7-11}

### Fixed {#v0-7-11-fixed}

- **Validator no longer fails BOM-prefixed concepts with E001:** the
  frontmatter splitter (`_split_frontmatter`) saw a leading UTF-8 BOM
  (`"\ufeff---"`) as the first line and — because `str.strip()` does not
  remove U+FEFF — concluded the file had no frontmatter block, emitting
  a hard E001 ("no parseable YAML frontmatter block found"), while the
  bundle loader (`parse_frontmatter`, rule L22) has always stripped the
  BOM and loaded the concept fine.

## [0.7.10] — 2026-10-12 {#v0-7-10}

### Fixed {#v0-7-10-fixed}

- **W017 no longer warns on valid same-day afternoon windows:** the
  validator's empty-window check compared
  `parse_temporal(valid_until)`'s midnight with
  `parse_temporal(valid_from)`, while the retrieval engine evaluates a
  date-only `valid_until` with inclusive end-of-day semantics
  (`_parse_window_end`: the whole day through 23:59:59.999999 UTC).

## [0.7.9] — 2026-10-11 {#v0-7-9}

### Fixed {#v0-7-9-fixed}

- **Validator rejected valid concepts containing an indented `---`
  line:** the validator's frontmatter splitter closed the frontmatter
  block at *any* line that looked like `---`, while the bundle loader
  (rule M24) only accepts a closing fence at column 0 — an indented
  `---` inside a YAML block scalar is content, not a fence.

## [0.7.8] — 2026-10-10 {#v0-7-8}

### Fixed {#v0-7-8-fixed}

- **MCP documentation described a read-only server that no longer
  exists:** `docs/src/mcp.md` (and the built `docs/mcp.html` /
  `llms.txt`) called `okfsmith mcp` a "read-only MCP server", promised
  "your bundle is never modified", said it "exposes eight tools", and
  closed with "The server is fully **read-only** — there is no tool that
  writes, edits, or deletes concepts… without fear." All of that has
  been false since the governed write-back tools shipped in 0.4.1.

## [0.7.7] — 2026-10-09 {#v0-7-7}

### Fixed {#v0-7-7-fixed}

- **Public pages stated a release that was no longer current:** the
  project website (`docs/site/index.html`) said "Latest release v0.6.0"
  in its PyPI card and "okfsmith v0.6.0" in the footer, and the man page
  (`man/okfsmith.1`) still carried "okfsmith 0.1.0" in its `.TH` header
  — while the shipped package was already at 0.7.6.

## [0.7.6] — 2026-10-08 {#v0-7-6}

### Fixed {#v0-7-6-fixed}

- **Dashboard missing-deps hint named pre-0.6.1 dependency pins:** when
  the dashboard extras were missing, `okfsmith dashboard` told users to
  run `pip install "fastapi>=0.110,<0.122" "uvicorn>=0.29,<0.32"` —
  ranges entirely below the floors this package has declared since 0.6.1
  (`fastapi>=0.122,<0.143`, `uvicorn>=0.35,<0.55`), and the `<0.122`
  line pulls the starlette 0.50.x releases the 0.6.1 floor raise was
  made to escape.

## [0.7.5] — 2026-10-07 {#v0-7-5}

### Fixed {#v0-7-5-fixed}

- **Dashboard port probe gives the correct answer on Windows:**
  `find_free_port` probed with `SO_REUSEADDR`, which on Windows lets a
  probe bind a port another process is already listening on — so an
  occupied port was reported as free and `serve()` would then fail when
  uvicorn tried to bind it.

## [0.7.4] — 2026-10-07 {#v0-7-4}

### Fixed {#v0-7-4-fixed}

- **Dashboard launch no longer crashes at the top of the port range:**
  `find_free_port` scanned upward without bound, so when port 65535 was
  occupied the scan walked past the last valid port and died with a raw
  `OverflowError: bind(): port must be 0-65535` traceback.

### Added {#v0-7-4-added}

- **Test coverage for the dashboard launch layer:**
  `tests/test_dashboard_launch.py` (17 tests) pins `find_free_port`
  (free/occupied/exhausted/out-of-range), `serve` (loopback-only bind,
  access-log-off token hygiene, `--no-open`, browser-failure fallback,
  occupied-port fallback message), and the `dashboard` command's error
  exits (bad port, bad dir, missing deps, start failure).

## [0.7.3] — 2026-10-06 {#v0-7-3}

### Fixed {#v0-7-3-fixed}

- **Search index builds ~2x faster (stemmer memoization):** the BM25
  stemmer is a pure function called once per token, but token
  vocabularies repeat heavily, so `SearchIndex.from_bundle` re-ran the
  suffix-stripping logic ~millions of times per build — profiling showed
  `stem()` dominating index-construction time (6M+ `endswith` calls for
  5,000 concepts).

## [0.7.2] — 2026-10-05 {#v0-7-2}

### Added {#v0-7-2-added}

- **Test coverage for the dashboard background-job manager:** the SSE
  job infrastructure (`okfsmith.dashboard.jobs` — `Job` lifecycle, step
  timing, terminal `{"status": ...}` publication, `JobManager`
  submit/evict/list, `sse_format`, `new_id`) previously had a single
  retention test; it is now pinned by `tests/test_dashboard_jobs.py` (22
  tests).

## [0.7.1] — 2026-10-04 {#v0-7-1}

### Fixed {#v0-7-1-fixed}

- **Shared section-concept link resolution for `graph` and W001** — links
  written in a per-section concept (id `doc/section`) are relative to the
  source *document*, but only the dashboard's Explore graph applied that
  rule — `okfsmith graph` reported such links as dead and `validate` raised
  a spurious W001. The rule now lives in the shared `okfsmith.links`
  resolver, so `graph`, the dashboard graph, and W001 agree: a target naming
  a whole document split into sections resolves to its primary section
  concept. Genuinely broken links are still dead.

## [0.7.0] — 2026-10-03 {#v0-7-0}

### Added {#v0-7-0-added}

- **Native Anthropic Messages API backend** — `--provider anthropic`
  (or just `ANTHROPIC_API_KEY` with nothing else configured) now speaks
  Anthropic's native API directly: no OpenAI-compatible proxy needed.
  Default model `claude-haiku-4-5`; system prompts use the API's native
  `system` parameter.

## [0.6.1] — 2026-10-01 {#v0-6-1}

### Fixed {#v0-6-1-fixed}

- **CI audit gate red: dependency security floors.** The `pip-audit`
  step in CI failed on published advisories: `fastmcp` 2.13.0.2
  (PYSEC-2026-2474, PYSEC-2026-2475, PYSEC-2026-2476,
  GHSA-rcfx-77hg-w2wv) and `starlette` 0.50.x (PYSEC-2026-161,
  PYSEC-2026-248, PYSEC-2026-249, PYSEC-2026-2280, PYSEC-2026-2281).

## [0.6.0] — 2026-10-01 {#v0-6-0}

### Added {#v0-6-0-added}

- **Similarity-based entity resolution in the extraction pipeline:**
  dedup (`_find_duplicate`) gains a third branch after exact
  normalized-title match and same-resource match — a Jaccard coefficient
  over stemmed title tokens (`title_similarity`, reusing the search
  module's tokenizer + stemmer), merging candidates at similarity ≥ 0.8
  with deterministic id tie-breaking.

## [0.5.2] — 2026-09-29 {#v0-5-2}

### Fixed {#v0-5-2-fixed}

- **Dashboard frontend missing from the PyPI wheel** — the 0.5.1 wheel
  shipped only the dashboard's Python files, so a pip-installed
  `okfsmith dashboard` showed the "frontend bundle has not been built yet"
  placeholder instead of the SPA. The `okfsmith/dashboard/static/*` bundle
  now ships in wheels and sdists, guarded by regression tests.

## [0.5.1] — 2026-09-28 {#v0-5-1}

### Fixed {#v0-5-1-fixed}

- **Knowledge-graph edge resolution for section concepts** — when a
  document is split into per-section concepts (id `doc/section`),
  markdown links in those concepts are relative to the source
  *document*, but the resolver treated the id as a file path, so the
  Explore graph silently dropped edges for interlinked documents. Links
  now resolve to the target document's primary section concept;
  genuinely broken links are still marked dead.

## [0.5.0] — 2026-09-28 {#v0-5-0}

### Added {#v0-5-0-added}

- **Web dashboard (`okfsmith dashboard`)** — a local-first web UI covering
  all ten product areas: Overview, Ingest (drag-and-drop with live
  parse → chunk → embed → validate → index progress), Explore
  (interactive knowledge graph), Temporal, Chat (grounded, with clickable
  citations), Validate, MCP, Eval, Doctor, and Settings. Binds only to
  `127.0.0.1`, per-launch token auth, default port 8931 with free-port
  fallback, fully offline packaged assets (no CDN). The knowledge graph
  renders ECharts-style: solid cluster-colored circles with labels
  inside, degree-scaled hubs, edge-to-edge arrows, and a cluster legend.
  See [Web dashboard](dashboard.html).

## [0.4.1] — 2026-09-28 {#v0-4-1}

### Fixed {#v0-4-1-fixed}

- **Runtime `__version__` mismatch:** `okfsmith --version` and the chat
  startup banner reported `0.3.2` because `src/okfsmith/__init__.py` was
  never bumped in the v0.4.0 release commit (only `pyproject.toml` was).

Fixed in this cycle from the pre-release QA audit (full details in the
QA bug report); criticals and highs listed, mediums/lows summarized.

- **Adversarial QA, final pass — MCP concurrent-create race (HIGH):**
  simultaneous `write_concept` calls for the same slug could all report
  success — the check-then-write (`exists()` → `os.replace`) let N
  threads pass the existence check before any rename, so losers silently
  clobbered the winner while each appended an audit entry.

- **Adversarial QA, final pass — sync dedup-shared update (HIGH):** when
  an updated file dedup-skipped against a donor's identical content, the
  state entry kept the OLD digest and the old concepts' ids (the donor
  fallback only applied when no stale ids were found).

- **Adversarial QA, final pass — temporal chain resolution (HIGH):**
  `SupersessionIndex.resolve_head` enumerated all simple paths with no
  memoization — exponential blowup on branching DAGs from frontmatter
  (32 concepts: `list` 18.7s, `search` 17.7s; 40 nodes ≈ minutes).

- **Adversarial QA, final pass — symlinked sync source (MEDIUM):**
  syncing through a symlinked source root printed "skipped: source is a
  symlink" and then deleted every concept synced from the real directory
  (the resolved path still scoped the deletions).

- **Adversarial QA, final pass — watch-mode staleness (LOW):** the
  mtime+size fast path is blind to a same-size edit with a preserved
  mtime.

- **Adversarial QA, final pass — eval threshold types (LOW):**
  `run_eval()` with a wrongly-typed `metric_threshold` (`"0.9"`,
  `[0.9]`, `{"context_relevancy": "high"}`, `True`) or `fail_under`
  (`"50"`, `nan`) leaked a raw `TypeError`; all such inputs now raise
  `EvalError("bad-threshold")` (the CLI already rejected them with exit
  2).

- **Adversarial QA, final pass — eval golden-set sanity (MEDIUM):** the
  golden `expected_answer` was never compared against the bundle — a
  fabricated reference answer passed the gate with full confidence.

- **Adversarial QA, final pass — MCP write-back (1 MEDIUM, 4 LOW):**
  `_reload_bundle` now evicts in-memory phantom concepts backed by
  `.preview-*.md` validation temps (a concurrent preview's temp file
  could previously be served by `get`/`list`).

- **MCP expansion (reviewer-1, 10 findings on the P6 MCP expansion):**
  continuation-token paging is now computed over result *items* only —
  notes and `##` section headers no longer consume the `max_chunks`
  budget, "N more" counts remaining items, and follow-on pages rebuild
  page 1 with the same unit-only budget, so paged output round-trips to
  exactly the unpaged item output.

- **Sync hardening (reviewer-1, 10 findings on `okfsmith sync`):**
  symlinked sources are now skipped with a per-file warning row instead
  of ingesting outside content (resolved-outside paths can never enter
  the sync state).

- **Critical (10):** symlink escapes confined to the bundle root in
  `ensure_index`/`append_log` (C1); concept ids `index`/`log` no longer
  overwrite the reserved files (C2); same-stem files in different
  directories no longer silently overwrite each other on ingest (C3);
  non-mapping/invalid-YAML frontmatter is preserved, not silently
  discarded on load+resave (C4); UTF-16 sources no longer ingest as
  NUL-garbage concepts (C5); validator no longer follows symlinked `.md`
  files or blesses escaping links (C6); slug collisions no longer
  silently overwrite concepts (C7); non-UTF-8 `.md` now yields `error
  [unreadable-file]` naming the file instead of a `UnicodeDecodeError`
  traceback in `read`/`validate`/`list`/`graph`/`chat` (C8); impossible
  YAML dates report E001 instead of crashing with `ValueError` (C9);
  scalar `verified`/`tags` frontmatter (e.g. `verified: yes`) no longer
  crash MCP tools and CLI trust paths with `TypeError` (C10).

- **High (17):** unreadable directory-discovered files report a per-file
  "failed" row instead of aborting the batch with `PermissionError`
  (H1); concurrent ingests no longer lose index entries (H2); quadratic
  link regexes hardened against crafted-input DoS (H3); deep YAML
  nesting is caught instead of crashing with `RecursionError` (H4);
  text-only Notion exports (no `_files/` dir) are recognized (H5);
  nested ZIPs are parsed to documented depth 1 instead of being silently
  skipped (H6); `graph --output` no longer silently overwrites existing
  files (H7) and handles directory/missing-parent targets cleanly across
  formats (H8); `ingest` with a file path as the bundle emits `error
  [not-a-directory]` (H9); FIFO/non-file ingest sources get a clean
  error instead of `NotADirectoryError` (H10); `init` I/O failures
  surface `error [io-error]` (H11); directories named `*.md` no longer
  crash `list`/`read`/`validate` (H12); `read --format json` handles
  non-JSON-native frontmatter values (H13); null bytes in link targets
  no longer crash `graph` (H14); over-long titles are truncated to
  filesystem-safe lengths (H15); LLM transport failures retry instead of
  aborting the whole extraction run (H16); `Bundle.load` no longer hangs
  on a FIFO named `*.md` (H17).

- **Medium/low (30 + 25):** summary of the remaining audit fixes — BOM
  handling in titles/frontmatter (M9), latin-1 mojibake flagged not
  silently corrupted (M10), binary-file detection on ingest (M11),
  `--dry-run` dedup-manifest parity (M18), parse errors reported
  accurately instead of the stub-prevention message (M2), phantom
  `'---'` concepts from frontmatter'd sources (M3), non-UTF-8 filename
  log encoding (M8), `validate --strict` output matches its exit code
  (M7), titled-link W001/W002 false positives (M12),
  code-block/graph-vs-validator link disagreements (M13, L3), mermaid
  node-ID collisions (M15), `check()` no longer creates missing dirs
  (M16), chat `/model` typo no longer kills the REPL session (M25),
  `graph --format text` inflection and other low-severity polish
  (L1–L25); stale `--bundle` flag usage removed from the MCP README
  (M26).

- **okfsmith eval (reviewer-2, 4 findings on the P4 eval harness):** a
  golden `must_cite` concept that retrieval never surfaced now fails its
  question with a `retrieval` diagnosis (previously it silently passed
  whenever the metric scores cleared their thresholds); the run's judge
  mode is derived from the per-score method labels alone — a configured
  LLM judge whose every call fails reports `heuristic`, and `mixed` is
  reserved for genuinely mixed runs.

### Added {#v0-4-1-added}

- **`okfsmith eval` (P4):** golden-set evaluation harness — the RAG
  Triad (context relevancy, faithfulness, answer relevancy) per
  question, not just averages.

- **`okfsmith eval` golden-set sanity warnings:** every question now
  gets a non-gating reference-support check — when a non-empty
  `expected_answer` shares almost no vocabulary with the retrieved
  context, the question carries a `warnings` entry (rendered as `!`
  lines in CLI output and in the JSON report) asking a human to verify
  the golden record.

- **MCP governed write-back:** four new tools on the MCP server —
  `preview_write_concept` (side-effect-free dry run showing the exact
  id, file path, frontmatter with provenance block, and serialized
  content), `write_concept` (create), `update_concept` (patch
  title/body/sources/links, with `dry_run` diff previews), and
  `audit_log` (reads the append-only `<bundle>/.okfsmith/audit.jsonl`).

- **Temporal model (P2):** time-aware retrieval over `valid_from` /
  `valid_until` / `supersedes` / `last_verified` frontmatter.

- `okfsmith sync BUNDLE SOURCE...`: incremental synchronization (P1).
  Each source file is SHA-256 fingerprinted and diffed against
  `<bundle>/.okfsmith/sync-state.json`; only new, changed, renamed, or
  deleted files are processed.

- `okfsmith search BUNDLE QUERY`: BM25 full-text search over a bundle,
  stdlib-only (no new dependencies).

- Docs: new `docs/searching.md` user guide (query syntax, tokenization,
  field weights, JSON shape, CLI/MCP/chat parity); README CLI table now
  lists `search`, documents `list --type`, and shows the correct
  `okfsmith chat v0.3.0` banner.

### Deferred {#v0-4-1-deferred}

- Re-ingest pruning / ghost-concept cleanup (M1): superseded for the
  `sync` path — `okfsmith sync` now replaces concepts on update and
  deletes concepts for removed sources (see Added above).

- Validator line numbers (M29): cosmetic; `Finding` carries no line
  field by design.

- Byte-identical ingest output (L12): `generated.at` timestamps are
  inherently time-dependent; a frozen-time mechanism is needed.

## [0.4.0] — 2026-09-28 {#v0-4-0}

### Added {#v0-4-0-added}

- **`okfsmith sync`** — incremental sync of a bundle with its sources:
  SHA-256 change detection, `added` / `updated` / `renamed` / `removed`
  handling (renames detected by content hash, updates replace under the
  same ids — never `name-2` duplicates), atomic resumable state,
  `--watch` polling, `--dry-run`, `--format json`. See
  [Syncing sources](syncing.html).
- **Temporal knowledge model** — concepts carry `valid_from` /
  `valid_until` validity windows, `supersedes` replacement chains, and
  `last_verified` freshness; retrieval ranks by currency, and
  `--as-of <date>` on `search` / `eval` replays any instant. Superseded
  concepts are hidden by default, never deleted. See
  [Temporal model](temporality.html).
- **MCP expansion** — four new read tools: `traverse` (BFS link-graph
  expansion, depth ≤ 3, cycle-safe), `provenance` (concept → sources →
  ingest manifest), `diff` (bundle vs bundle or vs sync snapshot), plus
  evidence budgets on every tool (`max_chunks`, `max_tokens`,
  `continuation_token`) for bounded agent context. See
  [MCP server](mcp.html).
- **`okfsmith eval`** — golden Q&A eval harness: scores golden sets on the
  RAG Triad (context relevancy / faithfulness / answer relevancy),
  diagnoses failures as retrieval vs generation, runs heuristic (keyless)
  or LLM-judge, and gates CI with `--fail-under`. See
  [Evaluating bundles](eval.html).
- **Governed MCP write-back** — four new tools (`preview_write_concept`,
  `write_concept`, `update_concept`, `audit_log`) let agents contribute
  under code-enforced governance: writes always land at the `unverified`
  trust tier, human-reviewed concepts need explicit `downgrade_trust`,
  validator-gated, atomic, append-only audited. See
  [MCP server](mcp.html).

## [0.3.2] — 2026-09-28 {#v0-3-2}

### Fixed {#v0-3-2-fixed}

- PyPI project page was blank ("The author of this package has not
  provided a project description") on every release: the upload script
  only sent identity/digest fields, never the release metadata.

## [0.3.0] — 2026-09-26 {#v0-3-0}

### Added {#v030-added}

- **Interactive chat REPL** (`okfsmith chat`) — ask questions over your
  bundle in natural language, Claude-Code style: citations, slash
  commands (`/search`, `/read`, `/validate`, `/graph`, `/doctor`, …),
  extractive fallback when no LLM is reachable, and generative answers
  via Ollama or any OpenAI-compatible provider. See
  [Interactive chat](chat.html).
- **Any-model provider system** — 15 `--provider` presets
  (`ollama`, `lmstudio`, `openai`, `groq`, `mistral`, `deepseek`,
  `openrouter`, `together`, `fireworks`, `deepinfra`, `anyscale`,
  `perplexity`, `xai`, `gemini`, `agentrouter`), plus `--api-base` /
  `OKFSMITH_API_BASE` for any other OpenAI-compatible endpoint. Keys are
  never displayed, logged, or saved to disk. See
  [Providers & API keys](providers.html).
- **Chat startup UI** — Qwen/Claude/Antigravity-style makeover: gradient
  ASCII `OKFSMITH` banner, bundle-aware `kb ›` prompt, and `✦` answer
  markers. Piped and `NO_COLOR` output stays plain.
- **This documentation website** — the Claude-Code-style docs you are
  reading, now live at
  [bilal-junaid-jiwani.github.io/okfsmith](https://bilal-junaid-jiwani.github.io/okfsmith/)
  via GitHub Pages.

## [0.2.0] — 2026-09-26 {#v0-2-0}

### Added {#v020-added}

- `okfsmith doctor` — environment check covering dependencies, optional
  extras, Ollama reachability, and API-key status (keys are always
  reported as `set (hidden)`, never echoed).
- `--format json` output for `list`, `read`, `validate`, and `graph`
  for scripting and CI.
- `--dry-run` for `ingest` — parse and plan without writing anything.
- Shell completion via `okfsmith --install-completion` /
  `--show-completion`, plus a man page.
- Progress bars for long ingests.

### Fixed

- Graph viewer (`viz.html`) pointer-event bug — click and drag now work
  in the interactive visualization.
- README/CLI help-text mismatches — documented commands and flags now
  match the real CLI exactly.

### Security

- Link containment in ingested content.
- Zip-bomb guards on archive inputs.
- Symlink skipping during directory ingestion.
- Fixed a HIGH-severity CVE in the MarkItDown dependency.

## [0.1.0] — 2026-09-26 {#v0-1-0}

Initial public release: init/ingest/validate/list/graph CLI, OKF §11
validator, offline HTML graph viewer, MCP server, `okfsmith-build` skill
pack.

### Upgrade notes

Upgrade with `pip install --upgrade okfsmith`. No bundle migration is
needed — bundles created by earlier versions validate unchanged.
`okfsmith search`, `okfsmith get`, and `okfsmith completions` were never
CLI commands (search/get are MCP tools and chat slash commands;
completion uses `--install-completion`).

## Links {#links}

- Full release history with downloadable artifacts:
  [github.com/Bilal-Junaid-Jiwani/okfsmith/releases](https://github.com/Bilal-Junaid-Jiwani/okfsmith/releases)
- Source repository:
  [github.com/Bilal-Junaid-Jiwani/okfsmith](https://github.com/Bilal-Junaid-Jiwani/okfsmith)
