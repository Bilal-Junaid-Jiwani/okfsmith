---
type: Reference
title: Linking
description: Concepts link to each other with bundle-relative absolute paths; links are untyped and the surrounding prose explains each relationship.
tags: [okf, spec, linking]
sources:
  - id: spec-repo
    resource: https://github.com/GoogleCloudPlatform/open-knowledge-format
    title: OKF spec repository
    author: team:google-cloud
  - id: spec-md
    resource: https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md
    title: OKF v0.2 SPEC.md
    author: team:google-cloud
status: draft
---

# Linking

Relationships between concepts are ordinary Markdown links. A concept ID is its
file path minus `.md`, so links are written as bundle-relative absolute paths
like `/concepts/bundle.md`[^spec-md].

## Untyped links, typed prose

Links carry no type of their own — there is no `requires` or `prerequisite`
relation in the format. The prose around the link says what the relationship
means: this concept *requires* [Bundle](/concepts/bundle.md) as background,
*extends* [Frontmatter](/concepts/frontmatter.md) with examples, and is
*checked by* [Conformance](/concepts/conformance.md).

## Broken links are tolerated

A link that points nowhere does not break conformance: consumers must not
reject a bundle over broken cross-links[^spec-md]. It is still a quality
defect, and linters flag it — every link in this bundle resolves.

## Trust note

This concept is a first draft: it has no `generated` stamp and no `verified`
entries, so it sits in the **unverified** trust tier.

[^spec-repo]: OKF spec repository (matches `sources` id `spec-repo`).
[^spec-md]: OKF v0.2 SPEC.md (matches `sources` id `spec-md`).
