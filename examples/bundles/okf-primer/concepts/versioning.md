---
type: Reference
title: Versioning
description: Bundles declare their OKF version with `okf_version` in the bundle-root index.md; minor bumps add optional fields, major bumps may break.
tags: [okf, spec, versioning]
sources:
  - id: spec-repo
    resource: https://github.com/GoogleCloudPlatform/open-knowledge-format
    title: OKF spec repository
    author: team:google-cloud
  - id: spec-md
    resource: https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md
    title: OKF v0.2 SPEC.md
    author: team:google-cloud
  - id: aimem-okf
    resource: https://github.com/q-qp-p/ai-memory/blob/HEAD/docs/okf.md
    title: OKF conformance (2.0) — community notes on the v0.1 to v0.2 change
status: draft
---

# Versioning

OKF versions are `<major>.<minor>`: a minor bump introduces backward-compatible
additions (new optional fields, new conventional headings), while a major bump
may make breaking changes such as renaming required fields or changing reserved
filenames[^spec-md].

## Declaring the version

A bundle may declare the version it targets with `okf_version: "0.2"` in the
frontmatter of the bundle-root `index.md` — the only place frontmatter is
permitted in any `index.md`[^spec-md]. Consumers that do not understand the
declared version should attempt best-effort consumption rather than refusing
the bundle[^spec-md].

## From v0.1 to v0.2

The v0.2 revision superseded v0.1 with two breaking changes: the `timestamp`
field became `generated: {by, at}`, and the `# Citations` body section moved
into `sources` frontmatter[^aimem-okf]. Additive trust, lifecycle, and
provenance families arrived in the same revision.

## Trust note

This concept is a first draft: it has no `generated` stamp and no `verified`
entries, so it sits in the **unverified** trust tier.

[^spec-repo]: OKF spec repository (matches `sources` id `spec-repo`).
[^spec-md]: OKF v0.2 SPEC.md (matches `sources` id `spec-md`).
[^aimem-okf]: Community documentation of the v0.1 → v0.2 change (matches `sources` id `aimem-okf`).
