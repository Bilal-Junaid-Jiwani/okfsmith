---
type: Topic
title: Big-O Notation
description: The standard notation for describing the upper bound of an algorithm's running time or space as input grows.
resource: https://en.wikipedia.org/wiki/Big_O_notation
tags: [algorithms, analysis, complexity]
sources:
  - id: big-o-wiki
    resource: https://en.wikipedia.org/wiki/Big_O_notation
    title: Big O notation — Wikipedia
generated:
  by: okfsmith/0.1.0
  at: 2026-09-26T08:20:00Z
status: draft
---

# Big-O Notation

Big O notation describes the limiting behavior of a function: in computer
science it classifies algorithms by how their running time or space
requirements grow as the input size grows, giving an upper bound on that
growth[^big-o-wiki].

## Reading it

An algorithm that scans every element of a list once is O(n); one that halves
the remaining search space each step, like binary search, is O(log n)[^big-o-wiki].
The notation deliberately ignores constant factors and lower-order terms, so it
compares growth rates, not wall-clock speed.

## Where it is used

[CS 201](/courses/cs201.md) uses Big-O throughout to compare data structures,
and the [Sorting Algorithms](/topics/sorting.md) concept shows it in action:
quicksort averages O(n log n) but degrades to O(n²) in the worst case.

## Trust note

This concept was drafted by `okfsmith/0.1.0` and has not yet been human-reviewed;
the definitions above are cited, but the pedagogical framing is provisional.

[^big-o-wiki]: Big O notation — Wikipedia (matches `sources` id `big-o-wiki`).
