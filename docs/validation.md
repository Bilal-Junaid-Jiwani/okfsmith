# Validation & error codes

`okfsmith validate BUNDLE` checks every concept against the OKF v0.2 §11
conformance rules. Each finding carries a stable code, the file, a message,
and the spec section it maps to.

## Errors (fail the bundle)

| Code | Spec | Meaning |
|------|------|---------|
| E001 | §11.1 | no parseable YAML frontmatter block |
| E002 | §11.2 | `type` missing, empty, or frontmatter is not a mapping |
| E003 | §8 | non-root `index.md` must not contain frontmatter |
| E004 | §12 | `log.md` date heading is not a valid calendar date |

## Warnings (fail only with `--strict`)

| Code | Spec | Meaning |
|------|------|---------|
| W001 | §6.1 | broken link target not found in bundle |
| W002 | §8 | concept not reachable from any `index.md` entry |
| W003 | §4.1 | recommended frontmatter field missing |
| W004 | §5.1 | footnote reference `[^id]` has no matching `sources[].id` |
| W005 | §5.1 | `sources` entry missing `id` |
| W006 | §5.5 | content is stale: `stale_after` has passed |
| W007 | §12 | unknown `okf_version`; expected `"0.2"` |
| W008 | §5.1 | `sources` entry missing REQUIRED `resource` |
| W009 | §5.2 | `generated` / `verified` entry missing `by` |
| W010 | §10.2 | `type: Attested Computation` but REQUIRED `runtime` is missing |
| W011 | §5 | malformed `generated` / `sources` / `verified` / `usage_window` value |
| W012 | §13.1 | legacy v0.1 field (`timestamp`, `# Citations` list) — migrate to v0.2 |
| W013 | §9 | `log.md` date headings are not newest-first |
| W014 | §5.4 | unknown `status`; expected `draft` \| `stable` \| `deprecated` |
| W015 | §5.1 | duplicate `sources[].id` |
| W016 | temporal | malformed temporal field (`valid_from` / `valid_until` / `last_verified` not ISO-8601), or malformed/overlong `supersedes` |
| W017 | temporal | `valid_until` is before `valid_from` |
| W018 | temporal | `supersedes` names a concept id that does not exist in the bundle |
| W019 | temporal | `supersedes` forms a cycle (retrieval treats the cycle as unresolved) |
| W020 | temporal | `last_verified` is in the future |

W016–W020 are okfsmith's temporal-model advisories (`valid_from` /
`valid_until` / `supersedes` / `last_verified`) — advisory like all
warnings, never affecting conformance. See the
[Temporal model](https://bilal-junaid-jiwani.github.io/okfsmith/docs/temporality.html)
docs page.

## Machine-readable reports

```bash
okfsmith validate ./kb --format json
```

```json
{
  "status": "conformant",
  "concepts": 12,
  "error_count": 0,
  "warning_count": 2,
  "errors": [],
  "warnings": [{"code": "W001", "file": "a.md", "message": "...", "spec_ref": "§6.1"}]
}
```

`status` is `"conformant"` only when there are no errors (warnings are
allowed unless `--strict`).

## CLI error codes

Separate from validation findings: when a *command* fails, the message starts
with `error [CODE]:` and the exit code is 1 (2 for usage errors). Examples:

- `error [bundle-not-found]:` — path does not exist
- `error [not-a-bundle]:` — directory has no `index.md`
- `error [slice-not-installed]:` — an optional extra is missing, with the
  exact `pip install "okfsmith[<extra>]"` fix
- `error [llm-unavailable]:` — no model endpoint reachable

JSON-output commands emit `{"status": "error", "code": ..., "message": ...}`
instead of the text form when `--format json` was requested.
