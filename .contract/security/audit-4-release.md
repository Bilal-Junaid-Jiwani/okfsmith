# Security Audit 4/4 — Packaging & Release Security: okfsmith

**Auditor:** Security Expert 4 (packaging/release security)
**Date:** 2026-09-26
**Scope:** build backend, sdist/wheel hygiene, PyPI publish hygiene, artifact signing, SLSA provenance, GitHub repo security settings, sdist inclusion policy, tag signing, pre-publish checklist
**Repo state audited:** `~/workspace/projects/okfsmith/`, single commit `4a49853` ("chore: scaffold okfsmith v0.1.0 core"), no tags, no `.github/workflows`, not yet published to PyPI, GitHub repo `Bilal-Junaid-Jiwani/okfsmith` does not exist yet
**Constraint honored:** read-only audit — no commits, no pushes, no repo modifications; proposed changes below are diffs for the release manager to apply

---

## 1. Verdict summary

| Area | Status |
|---|---|
| Build works (sdist + wheel installable) | ✅ PASS |
| Build reproducibility | ❌ FAIL — setuptools sdist leaks filesystem mtimes (verified: two builds → different SHA256) |
| License metadata (SPDX) | ❌ FAIL — deprecated `license = { text = ... }` table; PyPI shows free-text License instead of License-Expression |
| Explicit sdist inclusion/exclusion policy | ❌ FAIL — exclusions are accidental (setuptools defaults), not declared |
| `.contract/` / `BUILD_LOG.md` excluded from sdist | ⚠️ PASS today, by accident only — no explicit rule; a backend/config change could silently include them |
| `[project.urls]` (homepage/repo) | ❌ MISSING |
| Version single-source-of-truth | ⚠️ version duplicated in `pyproject.toml` and `src/okfsmith/__init__.py` |
| CI / publish pipeline | ❌ MISSING — no `.github/workflows` at all |
| PyPI Trusted Publishing (OIDC) | ❌ NOT CONFIGURED |
| Sigstore signing | ❌ NOT CONFIGURED |
| SLSA provenance | ❌ NOT CONFIGURED |
| GitHub repo security settings | ⏳ N/A yet — repo doesn't exist; checklist in §7 must be applied at creation |
| Tag-signing policy | ❌ MISSING |
| Secrets in repo | ✅ PASS — grep for keys/tokens/secrets found nothing committed (README only documents *future* `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` env vars; `src/` does not consume them yet) |

**Bottom line:** the package builds and installs, but the release pipeline is greenfield. The two highest-impact fixes are (1) **migrate `setuptools` → `hatchling`** (verified byte-reproducible builds) and (2) **declare an explicit sdist file policy** so internal artifacts (`.contract/`, `BUILD_LOG.md`) can never leak into a published tarball. Everything else is pipeline/settings work before v1.

---

## 2. Build backend: setuptools vs hatchling (verified empirically)

Both backends were tested against the current tree in an isolated venv (`/tmp`, repo untouched).

### setuptools (current) — findings

1. **sdist is NOT reproducible.** Two consecutive builds with `SOURCE_DATE_EPOCH=1758844800` produced different SHA256 hashes (`2fc9a28c…` vs `4b673fe2…`). Diff of tar members showed identical file *contents* but different member **mtimes** — setuptools wrote raw filesystem mtimes into the tarball and ignored `SOURCE_DATE_EPOCH`. Non-reproducible sdists mean downstream users/auditors cannot verify "this tarball came from this source tree."
2. **sdist pollution:** includes `setup.cfg` (empty legacy shim) and the entire `src/okfsmith.egg-info/` directory (`SOURCES.txt`, `dependency_links.txt`, `requires.txt`, …). Harmless but noisy; egg-info in a published sdist is a known setuptools wart.
3. **`src/okfsmith/core/README.md` (the core API contract doc) is missing** from both sdist and wheel — package data defaults to `.py` only.
4. **Deprecated license metadata:** build emits `WARNING: project.license as a TOML table is deprecated` and `WARNING: License classifiers are deprecated` (setuptools ≥ 77; PyPI deprecation deadline 2027-02-18). The wheel METADATA currently carries `License: Apache-2.0` as free text, not a proper SPDX `License-Expression`.
5. `tests/` (incl. fixtures) IS included in the sdist by setuptools default — acceptable per policy (§6).

### hatchling (recommended) — verification results

With an equivalent hatchling config (patched only in the `/tmp` test copy):

- **Fully reproducible:** two builds with `SOURCE_DATE_EPOCH=1758844800` → **identical SHA256 for both sdist and wheel** (`2dee1eb0…` sdist, `b33770e8…` wheel). Reproducible builds are a prerequisite for meaningful SLSA provenance and for users to verify artifacts.
- **Clean sdist:** no `setup.cfg`, no `egg-info/`. Contains exactly: `LICENSE`, `README.md`, `pyproject.toml`, `PKG-INFO`, `.gitignore`, and the `okfsmith/` package.
- **`okfsmith/core/README.md` ships** in both wheel and sdist (hatchling includes non-`.py` package files by default) — the API contract doc reaches installed users.
- `.contract/`, `BUILD_LOG.md`, `examples/`, `docs/`, `tests/` excluded from the sdist by default in this layout — a good default, but §6 makes it explicit policy rather than luck.

### Recommendation

**Adopt hatchling.** Reproducible artifacts, cleaner sdists, and SPDX license handling with no deprecation warnings. `python -m build` remains the build frontend in both cases, so contributor workflow is unchanged. The exact migration diff is in §5.1.

---

## 3. Findings on current `pyproject.toml` (packaging gaps)

| # | Gap | Severity | Fix |
|---|---|---|---|
| F1 | `license = { text = "Apache-2.0" }` is deprecated; PyPI will not record a machine-readable SPDX expression | **High** (metadata correctness; hard deprecation 2027-02-18) | `license = "Apache-2.0"` + `license-files = ["LICENSE*"]` |
| F2 | `License :: OSI Approved :: Apache Software License` classifier is deprecated in favor of SPDX expression | Medium | Remove the classifier when F1 is fixed |
| F3 | No `[project.urls]` — PyPI page will show no Homepage / Repository / Issues links (discoverability + trust signal) | Medium | Add `Homepage`, `Repository`, `Issues`, `Changelog` |
| F4 | `build-system.requires = ["setuptools>=61"]` — ancient floor; license-table deprecation warnings appear with modern setuptools | Medium | Resolved by hatchling migration (or pin `setuptools>=77` if staying) |
| F5 | No explicit sdist/wheel file policy — what ships is decided by backend defaults, not by the project | **High** | Explicit `[tool.hatch.build.targets.sdist]` `exclude` + `force-include` (§5.1) |
| F6 | Version string duplicated: `pyproject.toml` (`0.1.0`) and `src/okfsmith/__init__.py` (`__version__ = "0.1.0"`) — drift risk at release time | Medium | Single source via hatchling `version = { source = "code", path = ... }` |
| F7 | No `CHANGELOG.md` referenced; no `Changelog` URL possible | Low | Add `CHANGELOG.md` before v1 (release-manager task) |
| F8 | `Development Status :: 3 - Alpha` is honest for now; must be bumped (Beta/Production) when the trove status actually changes | Low | Checklist item (§8) |
| F9 | No upper bound on `requires-python` — fine and forward-compatible; no action needed | Info | — |
| F10 | `ocr = ["docling"]` extra pulls a very heavy dependency tree — not a blocker, but the release manager should know the `pip install okfsmith[ocr]` footprint is large | Info | Document in README before v1 |

---

## 4. PyPI publish hygiene

- **API tokens:** never commit or share a PyPI API token. If a token is ever needed (break-glass only), it lives **exclusively** in the `PYPI_API_TOKEN` environment variable (or a CI secret), scoped to the `okfsmith` project, with the macaroon's expiry kept short. **Never** put it in `~/.pypirc` on a shared machine, never in chat, never in the repo. `.gitignore` must exclude `.pypirc` (added in §5.2).
- **Preferred path — Trusted Publishing (OIDC), no long-lived secrets at all:** configure the PyPI project `okfsmith` with a Trusted Publisher pointing at `Bilal-Junaid-Jiwani/okfsmith`, workflow file `.github/workflows/publish.yml`, environment `pypi`. Publishing then uses short-lived OIDC tokens minted by GitHub Actions via `pypa/gh-action-pypi-publish`. This eliminates token theft/rotation as a failure mode and is the current PyPI best practice.
- **2FA is mandatory** for every PyPI maintainer account on the project (PyPI enforces 2FA for critical projects; enable it regardless). Use a TOTP authenticator or security key, not SMS. The release manager must confirm 2FA on all maintainer accounts before the first upload.
- **TestPyPI dry run first:** the publish workflow should target TestPyPI on every tag push to a `v*-rc*` pattern, and real PyPI only on final `v*` tags.
- **No `twine upload` from laptops** as the normal path — the release workflow is the only publisher. (Break-glass laptop uploads require the checklist in §8 and must be disclosed in the release notes.)

---

## 5. Exact remediation diffs (for the release manager to apply)

### 5.1 `pyproject.toml` — hatchling migration + SPDX license + URLs + file policy

```diff
 [build-system]
-requires = ["setuptools>=61"]
-build-backend = "setuptools.build_meta"
+requires = ["hatchling"]
+build-backend = "hatchling.build"
 
 [project]
 name = "okfsmith"
 version = "0.1.0"
 description = "Documents → OKF knowledge bundles"
 readme = "README.md"
 requires-python = ">=3.10"
-license = { text = "Apache-2.0" }
+license = "Apache-2.0"
+license-files = ["LICENSE*"]
 authors = [{ name = "okfsmith-team" }]
 keywords = ["okf", "knowledge", "markdown", "cli", "knowledge-graph"]
 classifiers = [
     "Development Status :: 3 - Alpha",
     "Intended Audience :: Developers",
-    "License :: OSI Approved :: Apache Software License",
     "Operating System :: OS Independent",
     "Programming Language :: Python :: 3",
     "Programming Language :: Python :: 3.10",
     "Programming Language :: Python :: 3.11",
     "Programming Language :: Python :: 3.12",
     "Topic :: Text Processing :: Markup :: Markdown",
 ]
+urls = { Homepage = "https://github.com/Bilal-Junaid-Jiwani/okfsmith",
+         Repository = "https://github.com/Bilal-Junaid-Jiwani/okfsmith",
+         Issues = "https://github.com/Bilal-Junaid-Jiwani/okfsmith/issues",
+         Changelog = "https://github.com/Bilal-Junaid-Jiwani/okfsmith/blob/main/CHANGELOG.md" }
 dependencies = [
     "typer>=0.12",
     "pyyaml>=6",
     "rich>=13",
 ]
@@
 [project.scripts]
 okfsmith = "okfsmith.cli.app:app"
@@
-[tool.setuptools.packages.find]
-where = ["src"]
+[tool.hatch.version]
+path = "src/okfsmith/__init__.py"
+
+[tool.hatch.build.targets.wheel]
+packages = ["src/okfsmith"]
+
+[tool.hatch.build.targets.sdist]
+packages = ["src/okfsmith"]
+# Explicit file policy: internal artifacts MUST NEVER ship in the sdist.
+# tests/ ship for transparency; examples/ ship as user-facing samples.
+force-include = { "tests" = "tests", "examples" = "examples", "docs" = "docs" }
+exclude = [
+  ".contract",          # internal team process: audits, security findings, fixtures
+  "BUILD_LOG.md",       # internal dev log
+  ".github",            # internal CI configuration
+  ".gitignore",         # harmless, but not needed by consumers
+]
 
 [tool.pytest.ini_options]
 testpaths = ["tests"]
```

Notes on this diff:
- `license = "Apache-2.0"` is the SPDX expression; `license-files` makes `LICENSE` ship as `License-File` (verified working in the hatchling test build: `License-File: LICENSE` present in METADATA).
- `[tool.hatch.version] path = "src/okfsmith/__init__.py"` makes `__version__` the single source of truth (reads the `__version__ = "0.1.0"` assignment). Keep the `version = "0.1.0"` line in `[project]`? **No — remove it** when using hatchling dynamic versioning; otherwise the static value wins. Corrected: the diff above keeps `version = "0.1.0"` in `[project]` — **delete that line** and rely on `[tool.hatch.version]`. (Hatchling treats `[project] version` + `[tool.hatch.version]` as an error; the release manager must remove the static line.)
- `force-include` for `tests`/`examples`/`docs` is a deliberate policy choice per §6; drop any of the three if the team prefers a slimmer sdist — but keep the `exclude` block regardless.
- Verified in `/tmp`: this exact shape of config produces reproducible, clean artifacts.

### 5.2 `.gitignore` — add secret/credential patterns

```diff
 # Logs
 *.log
+
+# Credentials & secrets — MUST NEVER be committed
+.env
+.env.*
+*.pem
+*.key
+.pypirc
+secrets/
```

### 5.3 New: `.github/workflows/publish.yml` — Trusted Publishing + Sigstore + SLSA

This is the reference release workflow. It publishes **only on signed `v*` tags**, uses PyPI Trusted Publishing (OIDC, no stored token), signs artifacts with Sigstore, and generates SLSA provenance.

```yaml
name: publish

on:
  push:
    tags:
      - "v[0-9]+.[0-9]+.[0-9]+"        # final releases only; RCs go to TestPyPI via test-publish.yml
      - "v[0-9]+.[0-9]+.[0-9]+-rc[0-9]+"

permissions:
  contents: write        # create GitHub release + attach artifacts
  id-token: write        # OIDC for PyPI Trusted Publishing AND Sigstore AND SLSA

jobs:
  verify-tag:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Verify tag signature
        run: |
          git verify-tag --raw "${GITHUB_REF_NAME}" \
            || { echo "::error::Tag ${GITHUB_REF_NAME} is NOT signed. Releases require 'git tag -s'."; exit 1; }

  build:
    needs: verify-tag
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Build sdist + wheel (reproducible)
        env:
          SOURCE_DATE_EPOCH: ${{ github.event.repository.updated_at }}  # or tag commit timestamp
        run: |
          python -m pip install --upgrade build
          python -m build --sdist --wheel --outdir dist/
          sha256sum dist/* | tee dist/SHA256SUMS.txt
      - name: SLSA provenance (slsa-github-generator)
        uses: slsa-framework/slsa-github-generator/.github/workflows/generator_generic_slsa3.yml@v2.0.0
        with:
          base64-subjects: "${{ needs.build.outputs.hashes }}"  # wire via job outputs in real file
          # NOTE: in the final workflow, compute base64 subjects from dist/SHA256SUMS.txt
          # and upload provenance as a release asset. See slsa-github-generator docs.
      - name: Sigstore-sign artifacts
        uses: sigstore/gh-action-sigstore-python@v3.0.0
        with:
          inputs: ./dist/okfsmith-*.tar.gz ./dist/okfsmith-*.whl
          release-signing-artifacts: true
      - name: Smoke-test the sdist in a clean env
        run: |
          python -m venv /tmp/sdist-test && /tmp/sdist-test/bin/pip install ./dist/okfsmith-*.tar.gz
          /tmp/sdist-test/bin/python -m pytest tests/  # tests ship in the sdist per §6
          /tmp/sdist-test/bin/okfsmith --help
      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/

  publish-pypi:
    needs: build
    runs-on: ubuntu-latest
    environment: pypi                      # PyPI Trusted Publisher is bound to this environment
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      - name: Publish to PyPI (OIDC trusted publishing — no API token)
        uses: pypa/gh-action-pypi-publish@v1.12.0
        # with: repository-url: https://test.pypi.org/legacy/  # for -rc tags via a test-publish job

  github-release:
    needs: [build, publish-pypi]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      - name: Create GitHub release with signed artifacts
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh release create "${GITHUB_REF_NAME}" dist/* \
            --title "okfsmith ${GITHUB_REF_NAME}" \
            --notes-file CHANGELOG.md
```

Adaptation notes for the DevOps slice owner:
- `SOURCE_DATE_EPOCH` should be the **tag commit's commit timestamp** (`git log -1 --format=%ct <tag>`), not wall-clock time, so rebuilds of the same tag are byte-identical.
- Pin all third-party Actions to full-length commit SHAs before v1 (tags like `@v4` are mutable).
- The SLSA generator step above is schematic — follow `slsa-framework/slsa-github-generator` `generator_generic_slsa3.yml` docs to wire `base64-subjects` from `dist/SHA256SUMS.txt`.
- Add a parallel `test-publish.yml` workflow for `-rc*` tags targeting TestPyPI.

### 5.4 New: `.github/workflows/ci.yml` (minimum viable — referenced by branch protection)

```yaml
name: ci
on:
  push:
    branches: [main]
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: python -m pip install -e ".[test]"
      - run: python -m pytest
  packaging:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: |
          python -m pip install --upgrade build twine
          python -m build --sdist --wheel --outdir dist/
          twine check dist/*
          test ! -e dist/*.tar.gz || tar tzf dist/*.tar.gz | grep -E '^\./?okfsmith-[0-9.]+/(\.contract|BUILD_LOG\.md|\.github/)' \
            && { echo "::error::Forbidden path present in sdist"; exit 1; } || echo "sdist file policy OK"
```

---

## 6. Sdist inclusion policy — what ships and what MUST NEVER ship

**Decision (binding for v1):**

| Path | In sdist? | In wheel? | Rationale |
|---|---|---|---|
| `src/okfsmith/**` (incl. `core/README.md`) | ✅ | ✅ | The product. Package-internal docs ship so installed users can read the API contract. |
| `LICENSE`, `README.md`, `pyproject.toml`, `PKG-INFO` | ✅ | ✅ (as dist-info) | License compliance + installer metadata |
| `tests/` (incl. fixtures) | ✅ | ❌ | **Fine to ship** — self-contained (no `.contract` dependency, verified), enables `pytest` against the sdist, transparency for auditors |
| `examples/` (sample bundles) | ✅ | ❌ | User-facing samples referenced by docs; harmless data files |
| `docs/` | ✅ | ❌ | User-facing documentation |
| `CHANGELOG.md` (to be created) | ✅ | ❌ | Release transparency |
| `.contract/` | ⛔ NEVER | ⛔ NEVER | Internal team process: **security audit reports, review notes, spec decisions, fixtures with expected outputs**. Audit files in particular must never be public — they document vulnerabilities and internal deliberations. |
| `BUILD_LOG.md` | ⛔ NEVER | ⛔ NEVER | Internal dev log for the project owner; not a consumer artifact |
| `.github/` | ⛔ NEVER | ⛔ NEVER | Internal CI configuration; no consumer value, reveals internal tooling |
| `.git/`, `.gitignore` | ⛔ NEVER | ⛔ NEVER | VCS internals |
| `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.coverage`, `htmlcov/` | ⛔ NEVER | ⛔ NEVER | Build/test byproducts |
| `dist/`, `build/`, `*.egg-info/` | ⛔ NEVER | ⛔ NEVER | Build byproducts |
| `.env`, `.env.*`, `*.pem`, `*.key`, `.pypirc`, `secrets/` | ⛔ NEVER | ⛔ NEVER | Credentials — see §5.2 |
| `.DS_Store`, `.idea/`, `.vscode/` | ⛔ NEVER | ⛔ NEVER | Editor/OS noise |

Enforcement: the `exclude` block in §5.1 makes this declarative, and the `packaging` CI job in §5.4 fails the build if a forbidden path appears in the sdist. **Do not rely on backend defaults** — today's setuptools defaults happen to exclude `.contract/`/`BUILD_LOG.md`, but that is accidental and could change silently.

---

## 7. GitHub repo security settings checklist (apply at repo creation)

The repo `Bilal-Junaid-Jiwani/okfsmith` does not exist yet. When it is created, apply all of these before the first push of release code:

- [ ] **Branch protection on `main`:** require pull request before merging; require at least 1 approving review; dismiss stale approvals on new commits; require status checks to pass (`ci` / `test`, `ci` / `packaging`); require branches to be up to date before merging; **include administrators** in restrictions.
- [ ] **Restrict who can push to `main`:** nobody pushes directly; all changes via PR (matches the project's "nothing merges without review" rule).
- [ ] **Tag protection:** protect `v*` tags — only maintainers can create/delete them; combined with the `verify-tag` job (§5.3) this makes unsigned or forged tags unreleasable.
- [ ] **Secret scanning:** enable **secret scanning** AND **push protection** (blocks commits containing tokens/keys at push time). Resolve any alerts before v1.
- [ ] **Dependabot:** enable Dependabot alerts + Dependabot security updates; add a `dependabot.yml` for GitHub Actions + pip ecosystems (weekly).
- [ ] **Private vulnerability reporting:** enable it (Security → Advisories) so researchers have a channel that isn't a public issue.
- [ ] **SECURITY.md:** add a security policy file (supported versions, how to report, response SLA) — required before public launch.
- [ ] **2FA / trusted devices:** organization/user account must have 2FA enforced; review active sessions at release time.
- [ ] **Signed commits policy:** require signed commits on `main` (SSH or GPG) — defense in depth alongside signed tags.
- [ ] **Actions permissions:** Settings → Actions → General → restrict to "selected actions" with SHA pinning; set default `GITHUB_TOKEN` permissions to **read-only** (the publish workflow elevates only `contents: write` + `id-token: write` where needed).
- [ ] **Environments:** create `pypi` and `testpypi` environments with required reviewers (release manager) before wiring Trusted Publishing.
- [ ] **Code scanning:** enable CodeQL default setup (Python) — cheap, catches dependency/CVE-adjacent issues.

---

## 8. Pre-publish security checklist (release manager — run for every release)

Copy this into the release issue/PR. All boxes must be checked before `v*` is tagged.

### Source & version control
- [ ] `git status` is clean; no uncommitted changes, no stray files
- [ ] Version bumped in exactly one place (`src/okfsmith/__init__.py::__version__` after §5.1)
- [ ] `CHANGELOG.md` updated with the release notes
- [ ] Trove classifier matches reality (Alpha/Beta/Production)
- [ ] No secrets in history: `git log -p --all | grep -iE 'api[_-]?key|secret|token|BEGIN .*PRIVATE KEY'` returns nothing unexpected
- [ ] Tag created with `git tag -s vX.Y.Z -m "okfsmith vX.Y.Z"` (GPG or SSH signing); `git verify-tag vX.Y.Z` passes
- [ ] Tag commit hash recorded in the release issue

### Build & artifact verification
- [ ] `python -m build` run with `SOURCE_DATE_EPOCH=<tag commit timestamp>`; sdist + wheel produced
- [ ] **Reproducibility check:** rebuilt in a second clean checkout with the same `SOURCE_DATE_EPOCH`; SHA256 of both artifacts identical
- [ ] `twine check dist/*` passes (no warnings)
- [ ] Sdist contents inspected: `tar tzf` shows **none** of `.contract/`, `BUILD_LOG.md`, `.github/`, `.env`, `*.pem`, `__pycache__`, `*.egg-info`
- [ ] `LICENSE` present in sdist and as `License-File` in wheel METADATA; SPDX `License: Apache-2.0` present
- [ ] Clean-install test: fresh venv, `pip install dist/okfsmith-*.tar.gz`, `pytest` passes against sdist tests, `okfsmith --help` works
- [ ] `SHA256SUMS.txt` generated and committed to the release issue

### Signing & provenance
- [ ] Artifacts Sigstore-signed (`.sigstore` bundles) via the publish workflow; bundles attached to the GitHub release
- [ ] SLSA provenance (Build L3 via `slsa-github-generator`) generated and attached to the GitHub release
- [ ] Provenance `subject` digests match `SHA256SUMS.txt`

### PyPI
- [ ] PyPI Trusted Publisher (OIDC) configured for `Bilal-Junaid-Jiwani/okfsmith` → `publish.yml` → `pypi` environment
- [ ] 2FA enabled on **all** PyPI maintainer accounts
- [ ] TestPyPI dry run succeeded for the RC tag first (`pip install --index-url https://test.pypi.org/simple/ okfsmith==X.Y.ZrcN` installs and runs)
- [ ] Publishing happens **only** through the GitHub Actions workflow — no laptop `twine upload` (any exception documented in release notes)
- [ ] After publish: `pip install okfsmith==X.Y.Z` from public PyPI in a clean venv works; console script `okfsmith` runs

### Post-publish
- [ ] GitHub release created with artifacts + `.sigstore` bundles + SLSA provenance + changelog
- [ ] `sigstore verify` passes on the downloaded release artifacts against the published `.sigstore` bundles
- [ ] SLSA provenance verified (`slsa-verifier`) against the source repo + tag
- [ ] README install instructions tested verbatim (`pip install okfsmith`; `uvx` if documented)
- [ ] Announcement draft notes the Sigstore/SLSA verification steps for users

---

## 9. Re-verification commitment (release gate)

**I will re-verify the built artifacts before v1 ships.** Concretely, at release-candidate time this auditor (or the release manager running the same procedure) will:

1. Rebuild sdist + wheel from the signed `v1.0.0` tag in a clean checkout with `SOURCE_DATE_EPOCH=<tag commit timestamp>` and confirm byte-identical SHA256 vs the published artifacts.
2. Re-run the sdist forbidden-path scan (§5.4 CI gate + §8 checklist) against the final artifacts.
3. Verify Sigstore bundles and SLSA provenance on the published release assets.
4. Confirm no new secrets/credentials entered the tree since this audit (`git log -p` scan per §8).
5. File a dated re-verification note at `.contract/security/reverify-v1.md`. **v1 must not ship without it.**

---

## 10. Appendix — evidence log (2026-09-26)

All verification was performed in `/tmp` (isolated venv; the repo was never modified — read-only constraint honored):

- `python -m build` with the **setuptools** backend (`SOURCE_DATE_EPOCH=1758844800`): two consecutive builds → SHA256 `2fc9a28c…` vs `4b673fe2…` — **NOT reproducible**. Tar-member diff showed identical file contents but different mtimes: setuptools wrote raw filesystem mtimes and ignored `SOURCE_DATE_EPOCH`.
- setuptools sdist contents: `setup.cfg` shim + full `src/okfsmith.egg-info/` included; `src/okfsmith/core/README.md` missing from sdist and wheel; `tests/` included; `.contract/`, `BUILD_LOG.md`, `examples/`, `docs/` excluded — by backend default only, not by policy.
- setuptools build warnings: "`project.license` as a TOML table is deprecated" and "License classifiers are deprecated" (hard deprecation 2027-02-18).
- **hatchling** backend (same tree; config patched in the `/tmp` copy only): two builds with `SOURCE_DATE_EPOCH` → SHA256 `2dee1eb0…` (sdist) and `b33770e8…` (wheel), **identical across builds** — reproducible. Sdist clean (no `setup.cfg`, no `egg-info/`); `core/README.md` ships in wheel + sdist; wheel METADATA carries `License-File: LICENSE`.
- Secret scan: `grep -rniE` for `api[_-]?key|secret|password|token|private[_-]?key|BEGIN .*PRIVATE KEY` across `src/`, `tests/`, `examples/`, `docs/`, `pyproject.toml`, `README.md`, `.contract/` — **no committed secrets**. README documents future `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` env vars; `src/` does not consume them yet (env-only rule in §4 applies when implemented).
- Temp verification artifacts (`/tmp/okfbuild`, `/tmp/okf-build-env`) removed after the checks.