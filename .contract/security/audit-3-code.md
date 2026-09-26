# Security audit 3 — code-level review (okfsmith)

Auditor: SECURITY EXPERT 3 of 4 (fresh pass; a prior attempt errored before producing output).
Date: 2026-09-26. Trees reviewed: main repo `~/workspace/projects/okfsmith` plus all worktrees
`/tmp/wt-{cli,parsing,validate,extract,mcp,skill,viz}` (read-only; no commits, no pushes).

Scope: path traversal (untrusted zip ingest, concept-id → file-path mapping),
YAML deserialization, command/shell injection, ReDoS in link/section regexes,
XSS in `viz.html`, frontmatter-merge issues, MCP server input validation,
error messages leaking paths/secrets.

**No CRITICAL findings.** One HIGH (crash/DoS via link resolution), three MEDIUM,
several LOW. Most important patch is Finding 1 (links.py) — a one-line fix.

---

## Findings

| # | Sev | File:line | Issue | Exploit scenario | Exact patch |
|---|-----|-----------|-------|------------------|-------------|
| 1 | HIGH | `/tmp/wt-cli/src/okfsmith/links.py:57` (`resolve_link`) | Uncaught `ValueError` from `candidate.relative_to(root)` when a markdown link resolves to an **existing** `.md` file **outside** the bundle root. `base = source_path.parent / clean` happily walks up (`[x](../../evil.md)`); if that file exists, `is_file()` is true, suffix is `.md`, and `relative_to(root)` raises. | Attacker plants a concept whose body contains `[x](../../../../tmp/planted.md)` (file exists on victim's disk) → `okfsmith graph` / `okfsmith graph --format text` (via `orphans()`) crashes with traceback. DoS + information about host files (existence oracle: dead-link vs crash). | Wrap the conversion: `try:\n    rel = candidate.relative_to(root)\nexcept ValueError:\n    return "dead", None` — or pre-check `(candidate.resolve().is_relative_to(root))` and return `"dead", None` when false. |
| 2 | MEDIUM | `/tmp/wt-parsing/src/okfsmith/parsers/notion.py:93`, `/tmp/wt-parsing/src/okfsmith/parsers/office.py:137` | No decompression-bomb guard before `zf.extractall(tmp)`: total uncompressed size and member count are never checked. A few-KB zip can expand to GBs (disk exhaustion in `/tmp`) or thousands of members (each parsed into memory in `_parse_zip`). | User ingests an untrusted Notion-export zip or generic `.zip` (the CLI's whole purpose) → disk/memory exhaustion, process OOM. | Before `extractall`, sum sizes and refuse over a cap: `infos = zf.infolist()\nif sum(i.file_size for i in infos) > 512 * 1024 * 1024 or len(infos) > 100_000:\n    raise ValueError("zip too large / too many members")` then extract. |
| 3 | MEDIUM | `/tmp/wt-parsing/src/okfsmith/core/bundle.py:80` (`Bundle.load`) | `rglob("*.md")` follows **file symlinks**: `md.read_text()` reads the link target. A bundle containing `evil.md -> /etc/passwd` (e.g. cloned from an untrusted source) gets its content parsed into concepts and embedded into `viz.html` / served over MCP / exported. | Attacker shares a malicious bundle repo; victim runs `okfsmith graph --format html` and publishes `viz.html` (or serves MCP) → local file contents exfiltrated into the output. | Skip symlinks at load: `for md in ...:\n    if md.is_symlink():\n        continue` (or `resolve()` + `is_relative_to(self.root)` containment check). |
| 4 | MEDIUM | `/tmp/wt-cli/src/okfsmith/cli/commands.py:199` (`ingest`) | Raw exception text interpolated into rich-markup output: `table.add_row(str(path), digest[:12], "0", f"[red]failed: {exc}[/red]")`. Exception text derives from the untrusted input filename/content (`parse_file` warns with `p.name`; parser errors echo names). Rich interprets `[...]` in the message. | Ingest a file named `[bold red]pwned.md` (or content that lands in an exception message) → rich markup injection into terminal output; unknown tags raise `rich.errors.MarkupError` → CLI crash (DoS). | `from rich.markup import escape` and use `f"[red]failed: {escape(str(exc))}[/red]"`. |
| 5 | LOW | `notion.py:93`, `office.py:137` (same lines) | Classic ZipSlip (`../` escape) is **not** live: this stdlib (`_extract_member`) strips `..`/absolute components on every supported Python (verified in 3.12.3 source + live test: `../../PWNED.txt` lands as `PWNED.txt` *inside* the target dir). The code still relies on *implicit* stdlib sanitization with no comment or explicit guard. | Defense-in-depth gap only: a future/custom extraction path or stdlib behavior change re-opens arbitrary file write (`~/.bashrc` → shell RCE on next login). | Add an explicit safe-extract helper used by both call sites: `for m in zf.namelist():\n    dest = (Path(tmp) / m).resolve()\n    if dest != dest and not str(dest).startswith(str(Path(tmp).resolve()) + os.sep):\n        raise ValueError(f"unsafe zip member: {m!r}")\n    zf.extract(m, tmp)` (skip directories appropriately). |
| 6 | LOW | `/tmp/wt-parsing/src/okfsmith/core/indexlog.py:31` (`_norm_subdir`) | `subdir.strip().strip("/")` does not reject `..`: `ensure_index(bundle, "..")` / `append_log(bundle, "..", ...)` compute `index_dir = bundle.root / ".."` and **write `index.md`/`log.md` outside the bundle root**. CLI never passes `subdir` (defaults `""`), so only reachable by library callers. | A downstream caller (or future CLI flag) passes `subdir=".."` → writes outside the bundle directory (file overwrite in parent dir). | `if posixpath.normpath(subdir) in ("..", ) or posixpath.normpath(subdir).startswith("../"):\n    raise ValueError(...)` at the top of `_norm_subdir`. |
| 7 | LOW | `/tmp/wt-extract/src/okfsmith/extract/human_review.py` (log call), `/tmp/wt-extract/src/okfsmith/extract/pipeline.py:354-359` | Log forgery: raw `reviewer` / `section.title` interpolated into `log.md` messages (`f'human review by "{reviewer}"...'`; `f'merged duplicate concept from section "{section.title}"...'`). Newlines in the value inject forged `##` headings / entries into the append-only log. | Malicious LLM output (section title) or reviewer string containing `\n## 2026-01-01\n- forged entry` → forged entries in the bundle's audit log. | Collapse whitespace before logging: `clean = " ".join(str(v).split())` for `reviewer` and `section.title` in log messages. |
| 8 | LOW | `/tmp/wt-extract/src/okfsmith/extract/human_review.py:31` | Error message leaks absolute bundle path: `raise KeyError(f"no concept {concept_id!r} in bundle at {bundle.root}")`. Only reaches local callers, but paths in exceptions tend to surface in logs/traces. | Minor information disclosure; no remote vector. | Drop the path: `raise KeyError(f"no concept {concept_id!r} in bundle")`. |
| 9 | LOW | `/tmp/wt-cli/src/okfsmith/links.py:113` (`mermaid_flowchart`) | Label sanitization replaces `"` but not `]`: a concept title containing `"]` breaks the `["label"]` mermaid node syntax (malformed chart output; not XSS in markdown renderers). | Crafted concept title → broken `okfsmith graph --format mermaid` output. | Also replace `]`: `label = f'{node["id"]} — {node["title"]}'.replace('"', "'").replace("]", ")")` (or escape per mermaid `#93;` entity rules). |
| 10 | LOW | `/tmp/wt-extract/src/okfsmith/extract/pipeline.py:345-347` (`_merge_concepts`) | Frontmatter-merge robustness: `sorted(set(merged_fm.get("tags") or []) | set(existing.frontmatter.get("tags") or []))` raises `TypeError` on mixed-type tags (ingest crash); a *string* `tags` value silently becomes a set of characters (data mangling). Not a classic vuln, but attacker-influenced frontmatter (LLM output) triggers it. | Malicious/careless frontmatter `tags: "abc"` + `tags: [1]` → crash or mangled tags on re-ingest. | Normalize first: `def _tag_list(v):\n    return [v] if isinstance(v, str) else [str(t) for t in (v or [])]` then `sorted(set(_tag_list(a)) | set(_tag_list(b)))`. |

---

## Clean bill — verified safe (with evidence)

- **YAML deserialization:** every YAML parse in all 7 trees uses `yaml.safe_load`
  (`core/frontmatter.py:36`, `validate/rules.py:54` via `_safe_yaml`). Grep for
  `yaml.load` / `yaml.full_load` / `yaml.unsafe_load` / `Loader=` across all trees: **zero hits**.
  Serialization uses `yaml.safe_dump`. Non-mapping YAML is coerced to `{}`.
- **Command/shell injection:** no `subprocess`, no `shell=True`, no `os.system`/`popen`,
  no `eval`/`exec`, no `pickle`/`marshal` anywhere in `src/` of any tree (grep-verified).
- **Concept-id → file-path mapping:** all writes go through `Bundle.write_concept` →
  `concept_path_for`, which **slugifies every segment** (`..` → `untitled`, backslashes
  normalized to `/`, leading `/` becomes an `untitled` segment) and joins onto the
  resolved bundle root — traversal-neutralized by construction. Reads via `Bundle.get`
  are dict lookups (MCP `get`/`neighbors` do **no filesystem access at request time**),
  so `concept_id="../../etc/passwd"` can only miss, never escape.
- **XSS in viz.html** (`wt-viz/src/okfsmith/viz/__init__.py`): `<title>`/`<h1>` use
  `html.escape`; every dynamic value injected via `innerHTML` in the detail panel,
  badges, and frontmatter table passes through the JS `esc()` (`&<>"'` escaped);
  the embedded JSON payload replaces `</` with `<\/` so no `</script>` breakout;
  `typeColor()` emits only `hsl(<uint>,…)` into the style attribute; ghost-node
  strings are fixed literals. Bodies/titles/frontmatter are all escaped at render.
- **ReDoS:** all link/section regexes (`links.py`, `wt-viz` `_INLINE_LINK_RE`/`_REFDEF_RE`,
  `validate/rules.py`, `parsers/sectioning.py`, `notion.py`, MCP `_LINK_RE`) use negated
  character classes with no nested quantifiers. Adversarial inputs (5k-char unclosed
  links, 2.5k bracket runs) timed at <0.1 s — linear.
- **MCP input validation** (`wt-mcp/.../mcp_server/server.py`): all five tools are
  read-only; `concept_id` is a dict key (no path join); `_bundle_links` normalizes
  only; `list`/`search` `limit` clamped via `max(limit, 0)`; unknown ids return
  plain-English `Error:` strings, never tracebacks; `build_server` raises
  `FileNotFoundError` for a missing bundle before loading anything.
- **Zip extraction (ZipSlip proper):** verified **not exploitable** — the stdlib's
  `_extract_member` strips `..` and absolute-path components (read the 3.12.3 source
  and ran a live `extractall` test: `../../PWNED.txt` landed *inside* the target dir).
  Zip *symlink* entries are extracted by `zipfile` as regular files containing the
  link target, so no symlink escape via extraction either. (Residual: Findings 2 & 5.)
- **LLM secrets** (`wt-extract/.../llm.py`): API keys come from env vars only
  (`OPENAI_API_KEY`), are redacted via `redact_key()` in the single debug log line,
  and `__repr__` explicitly excludes credentials. HTTP error messages include only
  the user-configured `base_url` and truncated server bodies — no key material.
- **Frontmatter merge** (`_merge_concepts`): dict-based, key order preserved, unknown
  keys pass through untouched per OKF v0.2 §11; `verified` entries are deduped by
  `(by, at)` tuples; existing verifications are preserved, never overwritten.
  (Robustness nits: Finding 10.)
- **Parser error handling:** `parse_file` never raises on corrupt input (warn + empty
  `ParsedDocument`); `_parse_zip` skips bad members individually; exception text is
  logged, **not** written into concept bodies. `ingest_no_llm` derives concept ids
  from `Path(source_id).stem` + `slugify(title)` — stem cannot contain separators.
- **Validate link resolution** (`validate/rules.py:95` `_resolve_target`): explicitly
  returns `None` when the normalized target escapes the bundle root (`..` check).

---

## Footer

Re-verification commitment: the findings above are against the worktree state as of
2026-09-26. I will re-review the **merged tree** (all slices landed) before v1 ships,
re-running the grep battery (`yaml.load`, `shell=True`, `subprocess`, `extractall`)
and re-testing Findings 1–4 against the merged code.
