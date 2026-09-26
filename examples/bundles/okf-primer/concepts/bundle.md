---
type: Reference
title: Bundle
description: An OKF bundle is a directory tree of UTF-8 markdown files in which every non-reserved file is one concept.
tags: [okf, spec, bundle]
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

# Bundle

A bundle is a directory tree of UTF-8 markdown files — no SDK, no runtime, no
database[^spec-md]. Every non-reserved `.md` file is exactly one concept, and a
concept's ID is its file path minus the `.md` extension (so this concept's ID
is `concepts/bundle`)[^spec-md].

## Reserved filenames

The filenames `index.md` and `log.md` are reserved and must never be used for
concepts[^spec-md]. Every concept carries a [Frontmatter](/concepts/frontmatter.md)
block, concepts connect through [Linking](/concepts/linking.md), and the whole
tree is judged by [Conformance](/concepts/conformance.md) rules.

## Trust note

This concept was drafted by `okfsmith/0.1.0` and has not yet been human-reviewed;
its spec claims are cited, but the framing is provisional.

[^spec-repo]: OKF spec repository (matches `sources` id `spec-repo`).
[^spec-md]: OKF v0.2 SPEC.md (matches `sources` id `spec-md`).
