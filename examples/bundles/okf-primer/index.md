---
okf_version: "0.2"
---

# OKF v0.2 in a Nutshell

An OKF v0.2 example bundle that explains the format itself. Each concept
describes one load-bearing idea of the Open Knowledge Format, with claims cited
to the spec repository.

## Concepts

* [Bundle](/concepts/bundle.md) - A bundle is a directory tree of UTF-8 markdown files; concept IDs come from file paths.
* [Frontmatter](/concepts/frontmatter.md) - `type` is the only required field; everything else is optional metadata.
* [Trust tiers](/concepts/trust-tiers.md) - Unverified, machine-confirmed, and human-reviewed, derived from `generated` and `verified`.
* [Conformance](/concepts/conformance.md) - The three hard rules of OKF v0.2 §11, and what consumers must tolerate.
* [Linking](/concepts/linking.md) - Bundle-relative absolute links, untyped; prose explains each relationship.
* [Versioning](/concepts/versioning.md) - How bundles declare their OKF version, and what changed from v0.1 to v0.2.
