# Example bundles

Two sample OKF v0.2 bundles shipped with okfsmith. They demo the format, give
the validator something real to chew on, and show the trust-tier ladder in
action.

## cs-curriculum/ — a CS curriculum knowledge pack (7 concepts)

A small, fictional computer-science curriculum. Course sequencing is
illustrative demo content; factual claims about computer science are cited to
their sources.

| Concept | Type | Trust tier |
|---|---|---|
| `courses/cs101.md` | Course | human-reviewed |
| `courses/cs201.md` | Course | machine-confirmed |
| `topics/recursion.md` | Topic | human-reviewed |
| `topics/big-o.md` | Topic | machine-confirmed |
| `topics/sorting.md` | Topic | unverified |
| `instructors/grace-hopper.md` | Instructor | unverified |
| `resources/sicp.md` | Resource | human-reviewed |

Prerequisite links connect the concepts: `cs201` requires `cs101`, courses
introduce and reuse topics, and the textbook and instructor concepts are linked
from the courses that use them. Every directory carries an `index.md` and a
`log.md`.

## okf-primer/ — OKF v0.2 in a nutshell (6 concepts)

The format explaining itself: one concept per load-bearing idea, cross-linked.

| Concept | Type | Trust tier |
|---|---|---|
| `concepts/bundle.md` | Reference | machine-confirmed |
| `concepts/frontmatter.md` | Reference | machine-confirmed |
| `concepts/trust-tiers.md` | Reference | human-reviewed |
| `concepts/conformance.md` | Reference | human-reviewed |
| `concepts/linking.md` | Reference | unverified |
| `concepts/versioning.md` | Reference | unverified |

Spec claims are cited to `sources[]` entries pointing at the spec repository
(`https://github.com/GoogleCloudPlatform/open-knowledge-format`) and the
v0.2 `SPEC.md`.

## Trust tiers

Tiers derive from the `generated` and `verified` frontmatter fields:

- **Unverified** — no `generated`, no `verified` (first drafts).
- **Machine-confirmed** — `generated: {by: okfsmith/0.1.0, at: ...}` present, no `verified` yet.
- **Human-reviewed** — a `verified: [{by: human:bilal, at: ...}]` entry exists.

Both bundles exercise all three tiers.

## Validate

Once okfsmith is installed:

```bash
okfsmith validate examples/bundles/cs-curriculum
okfsmith validate examples/bundles/okf-primer
```

The validator implements the OKF v0.2 §11 conformance rules: every
non-reserved `.md` file must have parseable frontmatter with a non-empty
`type`, and the reserved `index.md`/`log.md` files must follow their defined
structure. Broken cross-links are warnings, never errors (spec §11) — but
every link in these bundles resolves.
