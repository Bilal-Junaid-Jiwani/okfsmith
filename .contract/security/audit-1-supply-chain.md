# Security Audit 1 — Dependency & Supply-Chain

**Auditor:** Security Expert 1 (dependency/supply-chain), okfsmith senior team
**Date:** 2026-09-26
**Scope:** all 8 `pyproject.toml` (master + worktrees `/tmp/wt-{cli,parsing,validate,extract,mcp,skill,viz}`), declared + imported dependency graph, CVE scan, license scan, secret sweep.
**Mode:** read-only on repo; no commits, no pushes.

## Secrets check (required top-of-report statement)

**No critical secrets or credentials found.** Swept `src/` and `tests/` in master and all 7 worktrees for private keys, `ghp_`/API-key/token patterns, AWS key IDs. Only hits: `api_key="<redacted>"` as a *test string* in `/tmp/wt-extract/tests/test_extract.py:487` (asserts the literal never leaks into error output — good), and a comment mentioning PyMuPDF licensing in `wt-parsing/src/okfsmith/parsers/pdf.py`. Nothing live.

## Dependency inventory (all 8 trees)

Master, wt-cli, wt-validate, wt-mcp, wt-skill, wt-viz are byte-identical on dependencies. wt-extract adds `httpx>=0.27`. wt-parsing (edited by the parsing builder mid-audit — file changed between first and second read) now declares liteparse + markitdown. **Assumed merged-tree state** = union below.

| Package | Version spec | Where | License (verified) | CVE status | Verdict |
|---|---|---|---|---|---|
| typer | `>=0.12` | core, all trees | MIT (repo; PyPI classifiers absent but MIT upstream) | none (OSV 0.27.2 clean) | ⚠️ spec too loose — see F-2 |
| pyyaml | `>=6` | core, all trees | MIT | none | ⚠️ spec too loose |
| rich | `>=13` | core, all trees | MIT | none | ⚠️ spec too loose |
| httpx | `>=0.27` | core (wt-extract only) | BSD-3-Clause | none (0.28.1 clean) | ⚠️ spec too loose |
| liteparse | `>=2` | core (wt-parsing) | Apache-2.0 (PyPI classifier) | none known (new pkg) | ⚠️ supply-chain surface — see F-3; raise floor |
| markitdown[docx,pptx,xlsx] | `>=0.1` | core (wt-parsing) | MIT (Microsoft) | **transitive CVEs — see F-1** | ❌ floor too low; heavy in core — see F-1, F-4 |
| fastmcp | `>=2.0` (mcp extra) | extra | Apache-2.0 | none (4.0.10 clean) | ⚠️ loose; transitive httpx2 ok |
| docling | *(no spec)* (ocr extra) | extra | MIT (verified LICENSE file) | none (2.130.0 clean) | ❌ unpinned — see F-2 |
| pytest | `>=8` (test extra) | extra | MIT | none (9.1.1 clean) | ⚠️ loose |
| PyMuPDF / fitz | — | nowhere | AGPL-3.0 dual / commercial | — | ✅ **absent everywhere, as required** |
| pypdf | — | nowhere (fallback not needed) | BSD-3-Clause | — | ✅ not required |
| setuptools | `>=61` (build-system) | all | MIT | n/a | low — see F-5 |

**Method:** `pip-audit` 2.10.1 run against a venv with all installable direct deps resolved at latest (typer 0.27.2, pyyaml 6.0.3, rich 15.0.0, fastmcp 4.0.10 + fastmcp-slim, mcp 2.2.0, httpx 0.28.1, pytest 9.1.1, 98 packages total): **0 vulnerabilities in any project dependency.** The 12 hits were all in the venv's own `pip 24.0` (PYSEC-2026-1795/1796/2875/2876/196/3721 — pip's tar/wheel extraction flaws), which is *installer tooling, not a project dependency*. liteparse/markitdown/docling could not be pip-installed here (512 MB /tmp tmpfs), so those three were checked via OSV.dev + PyPI metadata + web CVE research instead.

**Transitive license scan:** no AGPL/copyleft anywhere in the tree (direct or transitive). docling → docling-slim → pypdfium2 (BSD-3/Apache-2.0) + docling-parse (MIT) + docling-core (MIT) + docling-ibm-models (MIT) — no PyMuPDF. markitdown → mammoth, lxml, pandas, openpyxl, python-pptx, beautifulsoup4 — all permissive. fastmcp-slim → `httpx2`/`httpcore2`.

**Supply-chain identity checks (all pass):**
- `httpx2`/`httpcore2` in the venv are **legitimate, not typosquat**: they are Pydantic's maintained continuation of `httpx`/`httpcore` (BSD-3-Clause, `github.com/pydantic/httpx2`), pulled transitively by fastmcp-slim, mcp 2.2.0, and starlette. encode/httpx itself is not archived (last release 0.28.1, Dec 2024); pydantic's fork is where active development continues.
- All declared names are canonical PyPI names. No typosquat lookalikes (`typeer`, `pyaml`, `richa`, etc.).
- All packages install from PyPI (default index). No git URLs, no local paths, no non-PyPI indexes.
- Abandonment: all direct deps had releases in 2025–2026 (fastmcp 2026-09-25, docling 2026-09-22, typer 2026-08-28, rich 2026-04-12, pytest 2026-06-19, pyyaml 2025-09-29; liteparse 2.14.7 2026-09-22; markitdown 0.1.8 2026-09-21). None abandoned.
- No unlisted third-party imports in code: every runtime import (typer, yaml, rich, httpx, liteparse, markitdown, openpyxl-via-markitdown, fastmcp-lazy) is now declared after the wt-parsing fix. (`wt-extract`'s `from files…` was a comment fragment; `OCR` was a docstring word.)

---

## Findings

### 🔴 HIGH — F-1: `markitdown[docx,pptx,xlsx]>=0.1` floor admits versions with CRITICAL transitive CVEs

`markitdown<=0.1.3` pulls:
- **CVE-2025-11849** — mammoth < 1.11.0: directory traversal via crafted DOCX external image link (`r:link`) → **arbitrary file read** (CVSS 3.1 **9.3 Critical**). Fixed in mammoth 1.11.0.
- **CVE-2025-64512** — pdfminer.six ≤ 20250506: insecure pickle deserialization of CMap cache → **RCE** (CVSS 8.6) via crafted PDF (pulled by markitdown's `pdf`/`all` extras; affected markitdown ≤ 0.1.3). Patched in pdfminer.six ≥ 20251107.

Current markitdown 0.1.8 pins `mammoth~=1.11.0` (patched line, via the `docx` extra we use) and `pdfminer-six>=20251230` (via `pdf`/`all` extras, not in our extra set, but defense in depth). The danger is the **spec floor**: `>=0.1` lets a resolver pick 0.1.0–0.1.3 on a stale index/lockfile and ship both CVEs. A third-party security review (2026-09, nixxet/brainstorming) independently BLOCKED markitdown deployments on exactly these two CVEs.

Related: a researcher-reported markitdown DOCX **DoS** (sub-2 KB `.docx` → minutes of CPU / OOM; heap pointer leaked into output). MSRC closed it as "not a vulnerability" because markitdown treats input as trusted. okfsmith's parsing tier runs on *user-supplied* documents — the trust assumption does **not** transfer. Treat as a hardening requirement (timeouts/resource limits around conversion calls), flagged here for the security-expert-2/3 + QA passes.

**Remediation:** raise the floor and add a ceiling; see exact diff in "Remediation patches". Also see F-4 (move out of core).

### 🟡 MEDIUM — F-2: Unpinned / unbounded specs everywhere

- `docling` in the `ocr` extra has **no version constraint at all** (`ocr = ["docling"]`) — today's install pulls 2.130.0 with a ~60-package tree (torch, onnxruntime, transformers…). Any future docling release (major included) is accepted silently.
- Everything else is `>=` with no upper bound: `typer>=0.12`, `pyyaml>=6`, `rich>=13`, `fastmcp>=2.0`, `pytest>=8`, `liteparse>=2`, `httpx>=0.27`.
- Latent conflict: docling-slim's `standard` extra constrains `typer<0.27.0,>=0.19.0`, but okfsmith resolves typer to 0.27.2 today — installing `.[ocr]` forces pip to backtrack typer *down*. Not broken, but a reproducibility smell that a lockfile + compatible ranges would eliminate.

**Remediation:** bounded ranges per the patch below (`>=floor,<next-major`), plus `docling>=2.130,<3`.

### 🟡 MEDIUM — F-3: liteparse is a small, young supply-chain dependency in core

liteparse 2.14.7 (run-llama org, Apache-2.0, prebuilt wheels) has no published CVEs and **zero runtime dependencies** (only dev extras: pytest, mypy) — tiny blast radius, which is good. But it is a small, recently-published package carrying PDF-parsing attack surface (crafted PDFs are the classic RCE/DoS vector) with no CVE track record to evaluate and a single-org maintainer. Acceptable for Tier-1 *provided*: (a) floor pinned to a reviewed version (`>=2.14,<3`), (b) `pip-audit` runs in CI on every PR, (c) malformed-PDF fuzz/negative tests exist (flag for QA). No blocker.

### 🟡 MEDIUM — F-4: markitdown + liteparse landed in `dependencies` (core), not an extra

The wt-parsing builder added both to core `dependencies` while this audit ran (previously they were imported-but-undeclared — that gap is now closed, good). But markitdown's `docx/pptx/xlsx` extras drag in mammoth, lxml, pandas, openpyxl, python-pptx, olefile — a heavy, CVE-prone chain (see F-1) installed for *every* okfsmith user, even those who never parse Office files. The office.py docstring even says "Requires the package extra: markitdown[docx,pptx,xlsx]" — the code expects an extra, the manifest declares core. Inconsistent.

**Remediation:** move to a dedicated `office` extra (code already handles `ImportError` gracefully with a helpful message — the lazy-import pattern is correct). Keep liteparse in core (Tier-1 PDF path) or likewise gate it; recommendation: both behind extras, core stays `typer/pyyaml/rich` only.

### 🟢 LOW — F-5: No lockfile; no automated dependency scanning

No `uv.lock`, `requirements*.txt`, or `pip-compile` output in any tree. Reproducible installs are impossible to guarantee; F-1's "stale lockfile" scenario cuts both ways — with no lockfile there is no audited baseline at all. Build backend `setuptools>=61` is also unbounded (low risk, but pin it).

**Remediation:** commit a lockfile (`uv lock` → `uv.lock`) generated from the bounded ranges, and add a CI step `pip-audit --strict` (or `uv pip audit`).

### ✅ Explicitly checked and CLEAR

- **PyMuPDF is not a dependency anywhere** (direct, extra, or transitive) — deliberate, correct: PyPI lists it as "Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License", which violates the project's no-AGPL policy. The wt-parsing code comment agrees.
- **No AGPL/copyleft licenses** in the full transitive graph (all direct deps MIT/Apache-2.0/BSD-3; docling family MIT; markitdown chain permissive).
- **No typosquats, no non-PyPI sources, no abandoned packages.**
- **No live secrets** in any tree.

---

## Remediation patches (exact)

### Patch A — master + all worktrees' `pyproject.toml` (bounded ranges, pinned extras)

```diff
 [build-system]
-requires = ["setuptools>=61"]
+requires = ["setuptools>=68,<81"]
 build-backend = "setuptools.build_meta"
```

```diff
 dependencies = [
-    "typer>=0.12",
-    "pyyaml>=6",
-    "rich>=13",
+    "typer>=0.12,<0.28",
+    "pyyaml>=6,<7",
+    "rich>=13,<16",
 ]
```

```diff
 [project.optional-dependencies]
-mcp = ["fastmcp>=2.0"]
-ocr = ["docling"]
-test = ["pytest>=8"]
+mcp = ["fastmcp>=2.0,<5"]
+ocr = ["docling>=2.130,<3"]
+test = ["pytest>=8,<10"]
```

For wt-extract additionally: `"httpx>=0.27"` → `"httpx>=0.27,<1"`.

### Patch B — wt-parsing `pyproject.toml` (F-1, F-4: floor fix + move Office chain to an extra)

```diff
 dependencies = [
     "typer>=0.12",
     "pyyaml>=6",
     "rich>=13",
     # Tier-1 PDF parsing: liteparse (run-llama, Apache-2.0, prebuilt wheels).
     # Verified installable on PyPI 2026-09-26 (2.14.7). Fully offline:
     # constructed with ocr_enabled=False, never calls paid OCR APIs.
     # PyMuPDF deliberately avoided (AGPL).
-    "liteparse>=2",
-    # Office/misc formats (MIT). The docx/pptx/xlsx extras are needed for
-    # DOCX/PPTX/XLSX support (mammoth, python-pptx, openpyxl).
-    "markitdown[docx,pptx,xlsx]>=0.1",
+    "liteparse>=2.14,<3",
 ]
```

```diff
 [project.optional-dependencies]
 mcp = ["fastmcp>=2.0"]
 ocr = ["docling"]
 test = ["pytest>=8"]
+# Office formats (MIT). Floor >=0.1.5 is a SECURITY requirement:
+# markitdown<=0.1.3 pulls mammoth<1.11.0 (CVE-2025-11849, CVSS 9.3,
+# arbitrary file read via crafted DOCX) and pdfminer.six<=20250506
+# (CVE-2025-64512, RCE via crafted PDF). >=0.1.5 pins mammoth~=1.11.0
+# (patched) and pdfminer-six>=20251230 (patched).
+office = ["markitdown[docx,pptx,xlsx]>=0.1.5,<0.2"]
```

Note: `office.py` already raises a helpful "install okfsmith with its office extra" error on `ImportError`, so moving to the extra is behavior-compatible.

### Patch C — lockfile + CI gate (F-5)

```bash
# after applying A+B, in the merged tree:
pip install uv
uv lock            # commit the resulting uv.lock
```

```yaml
# .github/workflows/security.yml (new)
name: supply-chain
on: [push, pull_request]
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --locked --extra test
      - run: uvx pip-audit --strict
```

### Patch D — docling OCR extra conflict note (F-2)

No manifest change needed beyond the `docling>=2.130,<3` bound: pip will backtrack typer to `<0.27.0` when `.[ocr]` is installed (docling-slim requirement). Document in README/docs that the `ocr` extra pins typer to the 0.19–0.26 line. (No code incompatibility found: okfsmith uses basic typer features.)

---

## Summary table — final verdicts

| Severity | Count | IDs |
|---|---|---|
| Critical | 0 | — |
| High | 1 | F-1 (markitdown floor admits CVE-2025-11849 / CVE-2025-64512) |
| Medium | 3 | F-2 (unbounded specs), F-3 (liteparse supply-chain surface), F-4 (heavy Office chain in core) |
| Low | 1 | F-5 (no lockfile / no CI audit gate) |

**Top fix (do first):** apply Patch B — raise `markitdown` to `>=0.1.5,<0.2` and move it to an `office` extra. That single change eliminates the only HIGH: it closes the CVE-2025-11849 (CVSS 9.3) and CVE-2025-64512 (RCE) exposure window and removes a heavy, CVE-prone chain from every default install.

## Re-verification commitment

This audit covers the dependency manifests as of 2026-09-26 (mid-merge; worktrees are actively changing — wt-parsing's manifest was edited during the audit). **I will re-audit the fully merged tree before v1 ships**: re-run `pip-audit` against the merged lockfile, re-check all version floors, and confirm PyMuPDF is still absent and no new AGPL/copyleft or typosquat packages entered via merge.
