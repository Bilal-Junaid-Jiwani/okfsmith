---
type: Reference
title: Conformance
description: An OKF v0.2 bundle conforms when every non-reserved file has parseable frontmatter with a non-empty type and reserved files follow their structure.
tags: [okf, spec, conformance]
sources:
  - id: spec-repo
    resource: https://github.com/GoogleCloudPlatform/open-knowledge-format
    title: OKF spec repository
    author: team:google-cloud
  - id: spec-md
    resource: https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md
    title: OKF v0.2 SPEC.md
    author: team:google-cloud
generated:
  by: okfsmith/manual
  at: 2026-09-26T08:15:00Z
verified:
  - by: human:bilal
    at: 2026-09-26T08:46:00Z
status: stable
stale_after: 2027-09-26
---

# Conformance

Conformance in OKF v0.2 (§11 of the spec) is deliberately tiny. A bundle is
conformant if and only if[^spec-md]:

1. Every non-reserved `.md` file in the tree contains a parseable YAML
   frontmatter block.
2. Every frontmatter block contains a non-empty `type` field.
3. Every reserved filename (`index.md`, `log.md`) follows its defined structure
   when present.

That is all. When the trust, lifecycle, provenance, or computation families are
present, producers should follow the relevant sections — and consumers must
derive trust tiers and staleness only from the fields the spec defines[^spec-md].

## What consumers must tolerate

Consumers must **not** reject a bundle because of missing optional frontmatter
fields, unknown `type` values, unknown additional frontmatter keys, broken
cross-links, or missing `index.md` files[^spec-md]. A [Bundle](/concepts/bundle.md)
with a dead link is still a conformant bundle; the link is a quality issue, not
a conformance failure.

[^spec-repo]: OKF spec repository (matches `sources` id `spec-repo`).
[^spec-md]: OKF v0.2 SPEC.md (matches `sources` id `spec-md`).
