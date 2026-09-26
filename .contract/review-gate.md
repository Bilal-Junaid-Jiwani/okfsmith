# Merge-Gate Review — `integrate/wave2` → `master`

**Reviewer:** Staff Reviewer (okfsmith senior team, merge gate)
**Date:** 2026-09-26 · **Branch:** `integrate/wave2` @ `d60e76a` · **Base:** `master`
**Diff:** 75 files, +8059 insertions · **Mode:** read-only (no commits, no pushes)

## VERDICT: APPROVE — merge to master

The merged tree builds, the full test suite is green, the CLI smoke passes end to
end, every CLI command is wired to a real slice signature, and nothing in the
diff makes the tree *broken* (no wrong command signatures in code, no
reproducible crashes). The reviewer/UX round-1 findings are quality and polish
gaps, explicitly designated as builder-round-1 work — none of them break the
build, the tests, or the CLI contract. The one near-call (viz.html pointer-event
bug, Panel D critical) is a defect in a *generated artifact's* CSS, not in the
CLI contract (`graph --format html` exits 0 and writes a valid file); it is
builder item #1 below and must be fixed first in round 1.

The coordinator performs the merge. I did not merge.

---

## 1. Diff review (code quality, typing, docstrings, error handling)

- **Structure:** thin-CLI/fat-core holds. `cli/commands.py` (483 lines) wires input
  to slices via `_lazy_attr` with clean exit-1 messages; real logic lives in
  `core`, `parsers`, `extract`, `validate`, `viz`, `mcp_server`.
- **Typing:** 82 public functions scanned — 1 missing return annotation
  (`mcp_server/server.py:280 build_server`), 10 missing docstrings (all dunders or
  nested helpers like `node_id`, `flush`, `new_section`). Good shape for a merge.
- **Error handling:** consistent `error:` prefix, exit 1 on failures, no raw
  tracebacks on user errors. One broad `except Exception` in the per-file ingest
  loop is deliberate (per-file failure tolerance) — noted for builder refinement.
- **Spec contract** (`.contract/spec_decisions.md`) spot-checked against code:
  - Concept ID = path minus `.md` — matches (`bundle.py`).
  - Reserved files matched literally and case-sensitively: `md.name in
    RESERVED_FILES` (`{"index.md", "log.md"}`) — `Index.md` correctly treated as a
    concept per the locked decision.
  - E001 (no/unparseable frontmatter), E002 (missing/empty type), E003 (non-root
    index.md frontmatter), E004 (log.md frontmatter) all present; W001–W015
    present with §-cited messages.
  - Root `index.md` may carry only `okf_version`; `okf_version: 0.2` enforced.
- **Hygiene:** `compileall` clean, no merge-conflict markers, `yaml.safe_load`
  everywhere (no `yaml.load`/`Loader=`), no `subprocess`/`shell=True`/`eval`/
  `pickle` in `src/`. No secrets in tree or history deltas.

## 2. Test suite — GREEN

`python3 -m pytest tests/ -q` → **160 passed, 19 skipped** (4.99 s). The 19 skips
are intentional (`tests/test_validate.py:76` — fixture declares no trust tiers).
Note: `pip install -e .` was blocked by PEP 668 (externally managed environment);
the package was already installed editable pointing at the working tree, so tests
ran against the reviewed code.

## 3. CLI smoke — all exit 0

On a temp bundle (`/tmp/smoke`): `init` → `ingest --no-llm` →
`validate` → `list` → `graph --format html` — every command exit 0.
`ingest --no-llm` created 4 draft concepts from a real document (a <1000-char doc
correctly yields 0 concepts via the documented stub-prevention rule).
`validate` reported "Conformant: no errors, no warnings." `viz.html` written
(29 KB).

All 7 CLI commands verified against real slice signatures (no signature
mismatches — the integration contract mismatches flagged pre-merge were
adjudicated correctly):
`ingest_no_llm(bundle, parsed, source_id)`, `extract.run(bundle, sections,
model=...)`, `validate.check(path) → Finding.as_dict()`,
`viz.render_html(root, output)`, `mcp_server.serve(bundle, transport)`,
`parsers.parse_file`, `parsers.sectioning.section`.

## 4. Security audit cross-check (HIGH findings)

| Audit | Finding | Status in merged tree |
|---|---|---|
| 2 (secrets) | — | **CLEAN** — verified, no action |
| 3 #1 HIGH | `links.py` `resolve_link` ValueError crash | **Not fixed in code, but the crash does not reproduce** in the merged tree: `Path.relative_to` is lexical, so `kb/../../outside.md` never raises — I verified live. The underlying containment bug is real (out-of-root links return `("ok", "../../outside")`, a bogus id). → builder item 3 |
| 3 #2 MED | zip decompression-bomb guard (`notion.py`, `office.py` `extractall`) | Not fixed → builder item 3 |
| 3 #3 MED | symlink skip in `Bundle.load` (`rglob` follows file symlinks) | Not fixed → builder item 3 |
| 3 #4 MED | rich markup injection in ingest failure rows (`commands.py:255`) | Not fixed → builder item 3 |
| 4 F1 HIGH | `license = {text="Apache-2.0"}` deprecated, no SPDX expression | Not fixed → builder item 6 |
| 4 F5 HIGH | no sdist/wheel file policy (`.contract/`, `BUILD_LOG.md` could leak) | Not fixed → builder item 6 |
| 3 #5–#10 LOW | zip-slip defense-in-depth, `..` in `_norm_subdir`, log forgery, path in KeyError, mermaid `]`, tag-merge robustness | Not fixed → builder round 1 backlog |

Audit 3's "clean bill" items (YAML, shell injection, concept-id→path mapping,
viz XSS escaping, ReDoS, MCP input validation) were re-verified by inspection.

## 5. Reviewer/UX findings — blocking check

No reviewer/UX finding makes the merged tree broken under the gate criteria:
- **README ↔ CLI signature drift** (`ingest ./kb <source>` in README vs real
  `ingest SOURCE --bundle`) is docs-side drift, not a wrong signature *in code*.
  → builder item 2.
- **Panel D critical** (viz `#empty` overlay): confirmed present
  (`viz/__init__.py:225` `#empty { display:flex }` overrides UA `[hidden]`,
  `position:absolute; inset:0` last in DOM → swallows all pointer events on every
  bundle). Serious, but the CLI contract holds (exit 0, valid file); it is a UX
  defect in a generated artifact → builder item 1, fix first.
- All other findings (completions, man page, `--format` enums, progress bars,
  JSON contracts, docs, demo, CI, publication) are polish/DX → builder items.

---

## Builder round 1 — top 10 (deduped, ranked by impact)

1. **Fix viz.html pointer-event killer (Panel D critical).** `#empty
   { display:flex }` defeats the `hidden` attribute on every bundle; the overlay
   sits on top of the canvas and swallows all mouse interaction (click, drag,
   pan, panel close). Fix: `#empty { display:none }` +
   `#empty:not([hidden]) { display:flex; … }`; add a regression test. Then fix
   Panel D highs: legend encoding contradicts canvas (trust=shape, type=color —
   split legend), keyboard a11y (`tabindex`, arrows/`+`/`-`/`Esc`), text
   alternative (`role="img"` + aria-label + concept list).
2. **Align README with the real CLI (all 5 reviewers, Panel A B1).** README
   quickstart and command table show `ingest ./kb <source>` (bundle positional);
   the CLI requires `ingest SOURCE --bundle ./kb`. Panel A's recommended fix:
   make the bundle positional on `ingest` and `mcp` (`ingest <source>
   <directory>`), keep `--bundle` as a deprecated alias erroring with guidance.
   Add a test that executes README code blocks against Typer parsing so docs
   can't drift again.
3. **Apply security audit code fixes (audit-3 HIGH/MED, audit-4 HIGH).**
   `links.py`: containment check — return `("dead", None)` when the resolved
   target escapes the bundle root (also kills the bogus `../../outside` ids).
   Zip bomb cap before `extractall` in `notion.py`/`office.py` (total
   uncompressed size + member count). Skip symlinks in `Bundle.load`.
   `rich.markup.escape` on exception text in ingest failure rows. Packaging:
   `license = "Apache-2.0"` + `license-files`, and an explicit sdist exclude
   policy so `.contract/` and `BUILD_LOG.md` never ship.
4. **Harden CLI input validation (Panel A M1/M5/M6).** `--format` (and
   `--transport`) as `typer.Choice` enums (bad values → exit 2 usage errors, not
   late exit-1); validate all local args/flags/paths *before* any lazy slice
   import in every command (today `validate ./kb --format yaml` and `ingest`
   with a bad `--bundle` report misleading errors).
5. **Conflicting-flag and destructive-action guards (Panel A M2/M4).**
   `--model` + `--no-llm` → exit 2 error instead of silent ignore. `init --force`
   on a non-empty dir → print what will be overwritten and require confirmation
   (`typer.confirm(abort=True)`) unless `--yes`/`-y` is passed.
6. **Packaging & release hygiene (R2/R3/R5, audit-4).** Add ruff/black config +
   CI workflow (pytest on 3.10–3.12), migrate setuptools → hatchling, fix or
   remove README badges pointing at nonexistent PyPI/GitHub pages. PyPI/GitHub
   publication itself is an owner action — tag `BLOCKED-NEEDS-OWNER`.
7. **Machine-readable contract (R5-4, Panel A m5/m7).** `--format json` on
   `list` and `read` (today text-only); `validate --format json` gains top-level
   `{"ok", "error_count", "warning_count"}`; define stable error codes
   (`NOT_A_BUNDLE`, `CONCEPT_NOT_FOUND`, `SLICE_MISSING`, …) instead of
   free-form strings.
8. **Ingest UX for long runs (Panel A M3, R1, R5-6).** Rich progress (per-file
   ✓/✗ lines + bar, TTY-aware, `--quiet` to suppress), `ingest --dry-run`
   plan preview, and `okfsmith doctor` checking Ollama reachability / parser
   imports / bundle validity with exact install commands. Reword `_lazy_attr`
   errors to user-facing language.
9. **Shell completions + man page (R2/R3).** Replace `add_completion=False`
   with `okfsmith completions <bash|zsh|fish|powershell>` (self-generating,
   fzf/zoxide pattern) and ship a man page + install docs.
10. **Docs & demo (Panel C/E, R3/R4/R5).** Troubleshooting/FAQ section, docs
    index, CLI reference generated from `--help` (never hand-maintained),
    `okfsmith demo` one-command showcase + recorded terminal demo (asciinema/vhs)
    under the README hero.

**Pre-existing tree state (not mine):** `BUILD_LOG.md` has uncommitted
modifications; `.contract/{reviews,security,seo,ux}/` are untracked. I committed
nothing and pushed nothing.
