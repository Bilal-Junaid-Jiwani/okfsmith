---
type: Reference
title: Human-reviewed concept
description: Verified by a human actor, written as a bare mapping.
verified: { by: human:ahormati, at: 2026-06-25T09:00:00Z }
---

# Body

A single verifier written as one `{ by, at }` mapping without the list dash.
Consumers MUST normalize it to a one-element list (§5.2, §11), and since a
`human:` actor verified it, the trust tier is **human-reviewed** (§5.3).
