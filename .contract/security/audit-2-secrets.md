# Security Audit — Secrets & Credentials Hygiene (Expert 2 of 4)

- **Auditor:** Security Expert 2 (secrets hygiene)
- **Date:** 2026-09-26
- **Scope:** entire okfsmith repo + all 7 worktrees + full git history
- **Repo:** `~/workspace/projects/okfsmith/`, branch `master` (commit `271f1d3`)
- **Mode:** read-only (no commits, no pushes, no code changes made)

## Verdict: CLEAN — no live-looking credentials found

No API keys, tokens, passwords, private keys, `.env` files, or hardcoded
credentials were found anywhere in the repo, in any of the 7 worktrees, or in
git history. Three minor hygiene improvements are recommended (none are
leaks; none are blockers for v1).

---

## 1. Scan methodology

1. **Pattern sweep** over all 8 trees (`~/workspace/projects/okfsmith` +
   `/tmp/wt-{cli,parsing,validate,extract,mcp,skill,viz}`), excluding `.git/`,
   `.venv/`, `__pycache__`, `site-packages`:
   - Real-key regexes: `sk-[A-Za-z0-9_-]{20,}`, `ghp_…`, `gho_…`,
     `AKIA[0-9A-Z]{16}`, `xox[baprs]-…`, `-----BEGIN … PRIVATE KEY-----`,
     `AIza[0-9A-Za-z_-]{30}` → **zero hits**
   - `find` for `.env*`, `*.pem`, `*.key`, `credentials*`, `*secret*` → **zero
     hits** outside venv site-packages (third-party deps only)
   - Keyword sweep (`api_key|apikey|secret|password|token|bearer|private_key|
     client_secret|aws_` in `.py/.md/.toml/.json/.yaml`) → only design-doc
     mentions, env-var names, and code under review (see §3)
   - Placeholder sweep (`sk-test|fake-key|dummy-key|changeme|mysecret|hunter2`)
     → **zero hits** — no example keys that look real
2. **Git history**: `git log -p --all` across all 6 commits on master searched
   for the same patterns. One match: `api_key="<redacted>"` in
   `tests/test_extract_llm.py` — the literal placeholder string used as the
   fake key in the redaction test, not a real credential (§3, note 1).
3. **Design-claim verification**: read `/tmp/wt-extract/src/okfsmith/extract/llm.py`
   in full (248 lines); traced every key read, log call, and exception path;
   checked `pipeline.py` for the `api_key` param flow.
4. **Test/fixture/docs/examples** review: fixtures under `.contract/fixtures/`,
   `tests/`, `docs/`, `examples/bundles/` scanned for pasted credentials.
5. **GitHub skill**: read `~/workspace/skills/github/SKILL.md` and
   `bin/gh` in full to confirm token handling untouched.

## 2. Files / areas scanned

| Area | Result |
|---|---|
| `~/workspace/projects/okfsmith/` (master, 6 commits) | clean |
| `/tmp/wt-cli`, `/tmp/wt-parsing`, `/tmp/wt-validate` | clean |
| `/tmp/wt-extract` — `src/okfsmith/extract/llm.py` full read | clean, verified (§3) |
| `/tmp/wt-mcp` (incl. `.venv` third-party deps) | clean (venv matches are upstream packages) |
| `/tmp/wt-skill`, `/tmp/wt-viz` | clean |
| `git log -p --all` (all history) | clean (one benign placeholder hit) |
| `.contract/fixtures/`, `tests/`, `docs/`, `examples/bundles/`, `README.md` | clean — only env-var *names* (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) |
| GitHub skill `bin/gh` + `SKILL.md` | clean — surrogate auth, untouched |

## 3. Verification of design claims

**Claim: "LLM keys come from env vars ONLY."** — VERIFIED with one caveat.

- `llm.py::resolve_backend()`: key source is `OPENAI_API_KEY` env var, or the
  programmatic `api_key=` parameter of `pipeline.run()` (used by tests and
  library callers). No `open()`/`pathlib` read of any key file anywhere in
  the extract package. `grep -rn "open(" …/extract` shows no key-file loading.
- There is **no `--api-key` CLI flag** in any worktree — the CLI surface is
  env-only, which is the safer posture (a flag would leak through `ps` and
  shell history).
- **Dangling reference (minor):** the `LLMUnavailableError` message in
  `llm.py:246-248` says `export OPENAI_API_KEY=...` **"(or pass --api-key)"** —
  a flag that does not exist. Not a leak; a confusing error message. Exact fix
  in §4, fix 2.

**Claim: "`redact_key` covers all log/error paths."** — VERIFIED.

- `OpenAICompatibleBackend.chat()`: `logger.debug("POST %s model=%s (key=%s)",
  … redact_key(self._api_key))` — value never logged.
- `resolve_backend()`: `logger.info(… redact_key(key))` — value never logged.
- `__repr__` explicitly includes only name and model ("never includes
  credentials").
- Exceptions: `LLMResponseError` messages carry `base_url`, model, HTTP status,
  `type(exc).__name__`, and `response.text[:500]` — no key material.
  httpx exceptions do not serialize `Authorization` headers.
- Dedicated test `test_redact_key_and_error_hygiene` asserts a failed chat
  call's exception string contains no key material — **except** it uses the
  literal string `"<redacted>"` as the fake key, so the assertion
  `"<redacted>" not in str(excinfo.value)` cannot detect a real leak
  (a false pass by construction). Recommend fix 1 in §4.

**Claim: "no secrets in tests/fixtures."** — VERIFIED. Fixtures contain only
synthetic finance/incident markdown; tests use `"fake-model"` and mock
transports.

**Claim: "no secrets in docs/examples."** — VERIFIED. `README.md:102-103`
lists only env-var names; docs/OVERVIEW.md states the no-secrets policy.

**GitHub skill `bin/gh`:** untouched — auth via `dynamic_credentials`
(authd surrogate), `allowed_hosts=["api.github.com"]`, no raw token in code,
logs, or output. The skill doc explicitly forbids collecting or printing raw
credentials. Nothing to fix.

## 4. Findings & exact fixes (all non-blocking)

### Finding 1 — `.gitignore` does not cover `.env` / secret files (LOW)
A `.env` dropped in the repo root (e.g. by a contributor testing a hosted
endpoint) would be **committable**. Currently `git check-ignore .env` → not
ignored.

**Fix** (append to `~/workspace/projects/okfsmith/.gitignore`):

```gitignore
# Secrets — never commit
.env
.env.*
*.pem
*.key
credentials*.json
*secret*.json
```

### Finding 2 — dangling `--api-key` reference in error message (LOW)
`src/okfsmith/extract/llm.py:248` in `resolve_backend()` suggests
`"(or pass --api-key)"`, but no such CLI flag exists anywhere in the
codebase. Keep the CLI surface env-only.

**Fix** (in `llm.py`, inside the `LLMUnavailableError` message):

```python
# before
"      export OPENAI_API_KEY=... "
"(or pass --api-key)\n"
# after
"      export OPENAI_API_KEY=...\n"
```

(If a `--api-key` flag is ever added, prefer a `--api-key-file` or env-only
approach: a CLI flag value is visible in `ps` output and shell history.)

### Finding 3 — redaction test uses a self-defeating fake key (LOW)
`tests/test_extract_llm.py::test_redact_key_and_error_hygiene` passes
`api_key="<redacted>"`, so `assert "<redacted>" not in str(excinfo.value)`
cannot distinguish "redacted" from "leaked".

**Fix**:

```python
# before
backend = OpenAICompatibleBackend(
    base_url="http://fake",
    model="m",
    api_key="<redacted>",
    client=httpx.Client(transport=httpx.MockTransport(handler)),
)
with pytest.raises(LLMResponseError) as excinfo:
    backend.chat([{"role": "user", "content": "hi"}])
assert "<redacted>" not in str(excinfo.value)
# after
SENTINEL = "sk-test-SENTINEL-9f8e7d6c5b4a"  # distinct value; must never appear in logs/errors
backend = OpenAICompatibleBackend(
    base_url="http://fake",
    model="m",
    api_key=SENTINEL,
    client=httpx.Client(transport=httpx.MockTransport(handler)),
)
with pytest.raises(LLMResponseError) as excinfo:
    backend.chat([{"role": "user", "content": "hi"}])
assert SENTINEL not in str(excinfo.value)
```

## 5. Footer — re-verification commitment

Per the audit brief, I will **re-scan the merged tree plus the GitHub remote
before v1 ships**: repeat the pattern sweep, the `git log -p` history check
(including any squashed/merged PR commits), the `.gitignore` check, and a
fresh full read of `llm.py` key-handling paths. Any live-looking credential
found at that stage will be reported as **CRITICAL** with rotation guidance
before release.

---
*Audit file: `.contract/security/audit-2-secrets.md` — read-only audit; no repo
files were modified.*
