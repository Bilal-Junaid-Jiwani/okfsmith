---
type: Topic
title: Sorting Algorithms
description: Classic algorithms for ordering data, used as case studies in correctness and efficiency analysis.
tags: [algorithms, sorting, analysis]
sources:
  - id: quicksort-wiki
    resource: https://en.wikipedia.org/wiki/Quicksort
    title: Quicksort — Wikipedia
  - id: mergesort-wiki
    resource: https://en.wikipedia.org/wiki/Merge_sort
    title: Merge sort — Wikipedia
status: draft
---

# Sorting Algorithms

Sorting — arranging items in order — is the classic vehicle for teaching
algorithm analysis: the problem is easy to state, and the standard solutions
differ sharply in efficiency[^quicksort-wiki].

## Quicksort

Developed by Tony Hoare in 1959, quicksort picks a pivot element and
recursively partitions the remaining items around it[^quicksort-wiki]. Its
average-case running time is O(n log n), but a bad pivot choice degrades it to
O(n²) — a textbook illustration of [Big-O Notation](/topics/big-o.md).

## Merge sort

Merge sort splits the input in half, recursively sorts each half, and merges
the results — a pure divide-and-conquer algorithm built on
[Recursion](/topics/recursion.md)[^mergesort-wiki]. It guarantees O(n log n)
time in the worst case at the cost of extra memory.

## Where they are studied

Both algorithms are the capstone case studies of [CS
201](/courses/cs201.md), which uses them to teach analysis end to end.

## Trust note

This concept is a first draft: it has no `generated` stamp and no `verified`
entries, so it sits in the **unverified** trust tier.

[^quicksort-wiki]: Quicksort — Wikipedia (matches `sources` id `quicksort-wiki`).
[^mergesort-wiki]: Merge sort — Wikipedia (matches `sources` id `mergesort-wiki`).
