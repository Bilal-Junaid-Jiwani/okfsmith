---
type: Reference
title: Cited concept
description: A concept whose body cites a source id that is not declared.
sources:
  - id: real-src
    resource: https://example.com/real
    title: A real source
---

# Body

This claim is properly attributed.[^real-src]

This claim cites a source id that was never declared.[^ghost]

[^real-src]: A real source
[^ghost]: A source id with no matching `sources[].id`
