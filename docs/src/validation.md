---
title: Validation & error codes
eyebrow: User guide
description: Check your bundle against OKF v0.2 conformance — errors E001–E004, warnings W001–W020 (incl. the temporal-model advisories), trust tiers, and how to fix the common findings.
---

## Validate your bundle

```bash
okfsmith validate ./kb
```

A conformant bundle prints empty tables and exits with code 0 — even under `--strict`:

```
       Errors (0)
┏━━━━━━┳━━━━━━┳━━━━━━━━━┓
┃ Code ┃ File ┃ Message ┃
┡━━━━━━╇━━━━━━╇━━━━━━━━━┩
└──────┴──────┴────────┘
      Warnings (0)
┏━━━━━━┳━━━━━━┳━━━━━━━━━┓
┃ Code ┃ File ┃ Message ┃
┡━━━━━━╇━━━━━━╇━━━━━━━━━┩
└──────┴──────┴────────┘
Conformant: no errors, no warnings.
```

Validation checks OKF v0.2 §11 conformance. Findings come in two severities:

- **Errors (E001–E004)** — hard conformance failures. Any error means the bundle is *not* conformant.
- **Warnings (W001–W020)** — advisory only; they never affect conformance, and `--strict` treats them as failures when you want a clean bill of health. W016–W020 are okfsmith's own temporal-model advisories (see [Temporal model](temporality.html)).

> [!TIP]
> Validate after every ingest: `okfsmith ingest ./kb guide.md --no-llm && okfsmith validate ./kb`. New concepts are Drafts, but they should still be conformant.

## Errors E001–E004

| Code | What it means | Where in OKF |
|---|---|---|
| `E001` | Concept has no parseable YAML frontmatter block (missing, or not valid YAML) | §11.1 |
| `E002` | Frontmatter is not a YAML mapping, or the required `type` is missing/empty | §11.2 |
| `E003` | A non-root `index.md` contains frontmatter, or the bundle-root `index.md` frontmatter has keys other than `okf_version` | §8, §12 |
| `E004` | A `log.md` date heading is not ISO `YYYY-MM-DD` | §9 |

## Warnings W001–W020

W001–W015 are the spec's advisory warnings; W016–W020 are okfsmith's
temporal-model advisories (`valid_from` / `valid_until` / `supersedes` /
`last_verified`). All warnings are advisory — none affect conformance.

| Code | What it means | Where in OKF |
|---|---|---|
| `W001` | Body link target resolves to no file in the bundle (broken link) | §6.1 |
| `W002` | Concept not reachable from any `index.md` entry | §8 |
| `W003` | Recommended `title` / `description` missing from frontmatter | §4.1 |
| `W004` | Body footnote `[^id]` has no matching `sources[].id` | §5.1 |
| `W005` | A `sources` entry is missing `id` | §5.1 |
| `W006` | `now >= stale_after` — concept content is stale (informational) | §5.5 |
| `W007` | `index.md` declares an unknown `okf_version` (expected `"0.2"`) | §12 |
| `W008` | A `sources` entry is missing REQUIRED `resource` | §5.1 |
| `W009` | `generated` is missing REQUIRED `by`, or a `verified` entry is missing `by` | §5.2 |
| `W010` | `type: Attested Computation` without REQUIRED `runtime` | §10.2 |
| `W011` | Timestamp-valued keys not ISO 8601 with an explicit UTC offset, or malformed `generated` / `verified` / `sources` / `usage_window` | §5 |
| `W012` | v0.1 legacy `timestamp` field or body `# Citations` list still present | §13.1 |
| `W013` | `log.md` date headings not newest-first | §9 |
| `W014` | `status` is not one of `draft` / `stable` / `deprecated` | §5.4 |
| `W015` | Duplicate `sources[].id` within one concept | §5.1 |
| `W016` | Malformed temporal field (`valid_from` / `valid_until` / `last_verified` not ISO-8601), or malformed/overlong `supersedes` (max 100 entries) | temporal |
| `W017` | `valid_until` is before `valid_from` | temporal |
| `W018` | `supersedes` names a concept id that does not exist in the bundle | temporal |
| `W019` | `supersedes` forms a cycle (retrieval treats the cycle as unresolved) | temporal |
| `W020` | `last_verified` is in the future | temporal |

## Trust tiers

Every concept carries a trust tier (visible in `okfsmith list`):

| Tier | Meaning |
|---|---|
| `unverified` | Default — everything fresh out of `--no-llm` ingest. Draft material, not yet confirmed. |
| `machine-confirmed` | A machine process (LLM extraction, cross-checks) confirmed the content. |
| `human-reviewed` | A human reviewed and signed off on the concept. |

New concepts start as `type: Draft` with tier `unverified`. Promoting tiers is a review workflow you do by editing concept files — the CLI records what you assert; it doesn't second-guess it.

## Fixing common errors

**E001 — no parseable frontmatter**

- The concept file must start with `---`, then YAML, then `---`. Check for a missing closing fence or a tab character (YAML forbids tabs).

**E002 — frontmatter not a mapping / `type` missing**

- Every concept needs `type: <something>` in frontmatter (ingest writes `type: Draft`). Make sure the frontmatter parses to key/value pairs, not a list.

**E004 — log date heading not ISO**

- `log.md` headings must be calendar dates like `2026-09-26`, not `Sep 26` or `26/09/2026`.

**W002 — concept not reachable from index**

- Link the concept from an `index.md` entry so it's discoverable from the bundle's entry points.

**W011 — timestamp without UTC offset**

- Write timestamps as full ISO 8601 with offset: `2026-09-26T12:18:20+00:00`, not `2026-09-26 12:18` or a date without a timezone.

**W012 — legacy v0.1 fields**

- Rename `timestamp:` to the v0.2 field structure and move `# Citations` body lists into `sources` frontmatter.

**W014 — bad `status`**

- Use exactly `draft`, `stable`, or `deprecated` (lowercase).

> [!NOTE]
> Warnings never block conformance. Fix the E-codes first; treat warnings as a quality checklist. If warnings bother you in CI, gate on `okfsmith validate ./kb --strict` so they fail the build.

<details>
<summary>Advanced</summary>

- `--format json` — machine-readable output: `{"errors": [{"code", "file", "message"}], "warnings": [...]}`. Exit code 0 = conformant; non-zero when errors are present (or warnings, under `--strict`).
- `--strict` — treat warnings as failures. Verified: a conformant bundle still exits 0 under `--strict`.
- Exit codes are stable and scriptable: gate deploys on them in CI.
- `okfsmith chat ./kb` also exposes `/validate` as a slash command, so you can check conformance mid-session.

</details>

---

**Next: [Visualizing the knowledge graph →](graph.html)** — see your concepts as a link graph, find orphans and dead links.
