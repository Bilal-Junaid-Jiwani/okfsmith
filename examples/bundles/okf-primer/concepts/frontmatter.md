---
type: Reference
title: Frontmatter
description: Every concept carries YAML frontmatter in which `type` is the only required field and everything else is optional.
tags: [okf, spec, frontmatter]
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
  by: okfsmith/0.1.0
  at: 2026-09-26T08:20:00Z
status: draft
---

# Frontmatter

Every concept file opens with a YAML frontmatter block. `type` is the only
required field — types are unregistered, so consumers must tolerate unknown
values[^spec-md]. Recommended fields include `title`, a one-sentence
`description`, `resource`, and a `tags` list.

## Optional families

The spec adds optional metadata families that producers may use freely:

- **Provenance** — `sources[]` (each entry requires `resource`; may carry `id`,
  `title`, `author`, `usage_count`, `last_modified`), with per-claim attribution
  in the body via footnotes whose keys match a `sources[].id`[^spec-md].
- **Trust** — `generated: {by, at}` and `verified: [{by, at}]`; see [Trust
  tiers](/concepts/trust-tiers.md).
- **Lifecycle** — `status: draft | stable | deprecated` (absent means `stable`)
  and `stale_after: YYYY-MM-DD` (a concept is stale when today is on or past
  that date)[^spec-md].

Consumers must not reject a concept for missing any optional family[^spec-md].

## Trust note

This concept was drafted by `okfsmith/0.1.0` and has not yet been human-reviewed;
its spec claims are cited, but the framing is provisional.

[^spec-repo]: OKF spec repository (matches `sources` id `spec-repo`).
[^spec-md]: OKF v0.2 SPEC.md (matches `sources` id `spec-md`).
