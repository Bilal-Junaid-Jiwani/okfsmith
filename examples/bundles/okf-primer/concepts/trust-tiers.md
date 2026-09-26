---
type: Reference
title: Trust tiers
description: Trust tiers — unverified, machine-confirmed, human-reviewed — are derived from the `generated` and `verified` frontmatter fields.
tags: [okf, spec, trust]
sources:
  - id: spec-repo
    resource: https://github.com/GoogleCloudPlatform/open-knowledge-format
    title: OKF spec repository
    author: team:google-cloud
  - id: spec-md
    resource: https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md
    title: OKF v0.2 SPEC.md
    author: team:google-cloud
generated:
  by: okfsmith/manual
  at: 2026-09-26T08:12:00Z
verified:
  - by: human:bilal
    at: 2026-09-26T08:45:00Z
status: stable
stale_after: 2027-09-26
---

# Trust tiers

The spec itself defines the *fields* — `generated: {by, at}` records who or what
produced a concept and when, and `verified: [{by, at}]` records reviews[^spec-md].
Actors follow the convention `human:<id>` for people, `<producer>/<version>`
for tools, and `process:<id>` for pipelines[^spec-md]. The three trust tiers
used in this bundle are okfsmith's convention, derived from those fields:

| Tier | Rule |
|---|---|
| **Unverified** | Neither `generated` nor `verified` is present. |
| **Machine-confirmed** | `generated` is present (e.g. `by: okfsmith/0.1.0`) but no `verified` entry exists. |
| **Human-reviewed** | At least one `verified` entry from a `human:<id>` actor exists. |

A bare `verified` mapping (not wrapped in a list) must be treated as a
one-element list[^spec-md].

## Verification is not attestation

`verified` confirms the *definition* still matches policy — it is doc-level,
slow, and recorded in the bundle. Attestation confirms a single *run* produced
a value the sanctioned way — it is per-call, runtime, and not stored in the
bundle. Both exist because a stale definition can still attest cleanly, and a
freshly verified definition still requires attestation on each run[^spec-md].

[^spec-repo]: OKF spec repository (matches `sources` id `spec-repo`).
[^spec-md]: OKF v0.2 SPEC.md (matches `sources` id `spec-md`).
