---
title: Evaluating bundles
eyebrow: User guide
description: Measure whether your bundle answers well — okfsmith eval scores golden Q&A sets on the RAG Triad (context relevancy, faithfulness, answer relevancy), diagnoses retrieval vs generation failures, and gates CI releases.
---

## Evaluate your bundle

`okfsmith validate` checks that your bundle *conforms* to the spec. `okfsmith eval`
checks that it is *good*: you curate a set of golden questions with reference
answers, and okfsmith scores every question on the RAG Triad —

- **context relevancy** — the fraction of retrieved concepts relevant to the question,
- **faithfulness** — the fraction of the answer's claims supported by the retrieved context,
- **answer relevancy** — how directly the answer addresses the question.

```bash
okfsmith eval ./kb --init-sample   # write a starter <bundle>/eval/golden.json
okfsmith eval ./kb                 # score it (heuristic mode, no LLM needed)
okfsmith eval ./kb --format json   # machine-readable full report
okfsmith eval ./kb --fail-under 70 # CI gate: exit 1 when the score is below 70
```

The starter set is self-consistent by construction: each generated question
uses only its concept's own vocabulary, so `eval --no-llm` passes it on a
healthy bundle — edit the questions into curated ones from there.

## Golden sets

Golden sets live at `<bundle>/eval/golden.json` — a JSON list of question records:

```json
[
  {
    "id": "refund-window",
    "question": "How long do customers have to request a refund?",
    "expected_answer": "Customers get a full refund within 30 days.",
    "must_cite": ["policies/refunds"],
    "tags": ["policy"]
  }
]
```

Fields:

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Unique question id (used in reports). |
| `question` | yes | The question to ask the bundle. |
| `expected_answer` | no | Reference answer text (defaults to `""`). |
| `must_cite` | no | Concept ids a good answer *must* cite (defaults to `[]`). Drives the retrieval-vs-generation diagnosis. |
| `tags` | no | Free-form tags (defaults to `[]`). |

Malformed golden files fail cleanly (`error [golden-invalid]` /
`error [golden-schema]` with the line number or the offending record) —
never a traceback.

## Heuristic mode vs LLM judge

Every score is labeled with its method:

- **⚙ heuristic** — keyless, stdlib token-overlap scoring. Runs fully offline
  with `--no-llm` (or when no LLM is reachable). Crude but deterministic and honest.
- **🤖 llm-judge** — when an LLM backend is configured (same `--provider` /
  `--model` / `--api-base` / `--api-key` plumbing as `chat`), the judge LLM
  scores relevance and faithfulness directly, and answers are generated
  instead of extracted.

If a judge call fails, that metric degrades to the heuristic — the method
label always tells the truth, never the reverse. The run header states the
overall mode: `heuristic` when no metric was LLM-judged (including a
configured judge whose every call failed), `llm-judge` when every metric
was, and `mixed` only when some metrics were judged and others fell back.

## Retrieval vs generation: the actionable output

Averages hide the fix. `eval` reports **per question**, and every failing
question gets a diagnosis:

- **retrieval** — a golden `must_cite` concept was not retrieved, or nothing
  retrieved is relevant. Fix: improve ingest coverage, titles, or wording.
  An unretrieved `must_cite` concept fails its question even when every
  metric score passes its threshold.
- **generation** — the right concepts *were* retrieved but the answer failed.
  Fix: the answer construction / prompting, not the content.

Retrieval reuses the shared BM25 engine (same ranking as `search`, chat, and
MCP), including temporal behavior: superseded concepts stay hidden unless
`--include-superseded` is given, and `--as-of <date>` replays validity and
supersession chains at that instant — so a golden set can assert that stale
answers stay buried.

## CI gating

```bash
okfsmith eval ./kb --fail-under 70
```

Exit `0` when the overall score (0–100, the mean of per-question means)
clears the threshold, exit `1` when it doesn't. Per-metric pass thresholds
default to `0.6` for context relevancy and faithfulness and `0.4` for answer
relevancy (the heuristic's natural scale is lower); override all three with
`--metric-threshold <0-1>`. Use `--top-k` / `-n` to change how many concepts
each question retrieves.

**Next:** [CLI reference →](cli.html) — every flag of every command.

## What `expected_answer` does (and does not) prove

`expected_answer` is a *reference aid*, not a correctness oracle:

- In **heuristic mode** its vocabulary helps `context_relevancy` recognize
  relevant concepts; no metric compares the generated answer against it
  semantically. A golden record with a fabricated `expected_answer` can
  still pass — the gate measures **bundle** quality, not golden-set quality.
- In **LLM-judge mode** it is shown to the judge as reference context, but
  there is likewise no answer-correctness score against it.

To keep sloppy golden sets from buying false confidence, every question
gets a **golden-set sanity check**: when a non-empty `expected_answer`
shares almost no vocabulary with the retrieved context, the question is
flagged with a `!` warning (also in the JSON report's `warnings` field).
The warning never fails the question or the gate — it asks a human to
verify the golden record. Note the honest limit: a deliberately salted
fabrication (real bundle terms woven into a false answer) can evade this
keyless check; only a semantic comparison (LLM judge, or human review)
catches those.
