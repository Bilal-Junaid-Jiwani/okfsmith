---
type: Topic
title: Recursion
description: A technique where a function calls itself, reducing a problem to smaller instances of itself.
resource: https://en.wikipedia.org/wiki/Recursion_(computer_science)
tags: [programming, algorithms, fundamentals]
sources:
  - id: rec-wiki
    resource: https://en.wikipedia.org/wiki/Recursion_(computer_science)
    title: Recursion (computer science) — Wikipedia
generated:
  by: okfsmith/manual
  at: 2026-09-26T08:05:00Z
verified:
  - by: human:bilal
    at: 2026-09-26T08:40:00Z
status: stable
stale_after: 2027-09-26
---

# Recursion

Recursion is the technique of defining something in terms of itself: in
programming, a function that calls itself on a smaller input until it reaches a
base case that needs no further recursion[^rec-wiki].

## Why it matters

Recursion is the natural way to express divide-and-conquer algorithms and to
work with recursive data structures such as trees. It is introduced at the end
of [CS 101](/courses/cs101.md) and becomes a daily tool in [CS
201](/courses/cs201.md), where classic [Sorting Algorithms](/topics/sorting.md)
like merge sort are presented recursively.

## The classic example

The factorial function is the canonical illustration: `n! = n * (n-1)!` with
the base case `0! = 1`. Every recursive solution needs such a base case, or the
calls never terminate[^rec-wiki].

[^rec-wiki]: Recursion (computer science) — Wikipedia (matches `sources` id `rec-wiki`).
