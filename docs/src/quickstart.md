---
title: Quickstart
eyebrow: Getting started
description: Five minutes from zero to a validated knowledge bundle: init, ingest with --no-llm, validate, and graph — every command copy-paste ready.
---

## What you will build {#what-you-will-build}

In under five minutes you will create a knowledge bundle from a
document, check that it conforms to the OKF v0.2 specification, and look
at its concept graph. Every command below is copy-paste ready, and the
`--no-llm` flag means **no API key, no model, no internet** — it all
runs on your machine.

The four commands:

```bash
okfsmith init ./kb
okfsmith ingest ./kb guide.md --no-llm
okfsmith validate ./kb
okfsmith graph ./kb
```

## Step 1 — Create a document to ingest {#step-1-document}

First, make a small Markdown document. Run this exactly as written —
the file must be over ~1,000 characters (shorter files are skipped on
purpose, see [FAQ](faq.html#why-skipped)):

```bash
mkdir -p ~/okfsmith-demo && cd ~/okfsmith-demo

cat > guide.md <<'EOF'
# Getting started with okfsmith

okfsmith turns messy documentation into a structured knowledge bundle
using the Open Knowledge Format (OKF). A bundle is a folder of
Markdown files with machine-readable frontmatter, so everything stays
readable by humans and by agents alike.

## Installation

Install from PyPI with `pip install okfsmith`. You need Python 3.10 or
newer. Verify the install with `okfsmith --version` and
`okfsmith doctor`, which checks your dependencies, optional extras,
Ollama reachability, and whether your API keys are configured (it never
prints the keys themselves).

## Your first bundle

Run `okfsmith init ./kb` to create a bundle. Then run
`okfsmith ingest ./kb guide.md --no-llm` to ingest this very file.
The `--no-llm` flag uses deterministic sectioning: it splits documents
on headings and needs no API key and no model. It is the fastest way to
get a feel for the whole workflow.

## Validation

After ingesting, run `okfsmith validate ./kb`. It checks the bundle
against the OKF v0.2 specification: error codes E001 through E004 and
warning codes W001 through W015. A clean bundle exits with code 0.

## Trust tiers

Every concept carries a trust tier: `unverified`, `machine-confirmed`,
or `human-reviewed`. No-LLM ingests land at `unverified`, which tells
every reader exactly how much trust to place in the content. Promote
tiers as concepts get reviewed and confirmed.
EOF
```

> [!TIP]
> On Windows, save the file as `guide.md` with Notepad instead of using
> the `cat` command — then `cd` to that folder in PowerShell and continue
> from Step 2.

## Step 2 — Create the bundle {#step-2-init}

```bash
okfsmith init ./kb
```

```text
Initialized OKF bundle in kb
  index: /path/to/okfsmith-demo/kb/index.md
  log:   /path/to/okfsmith-demo/kb/log.md
Next: add sources with 'okfsmith ingest kb <file-or-dir> --no-llm'.
```

A bundle is a folder. `init` creates exactly two files inside it:
`index.md` (the bundle manifest) and `log.md` (the activity log).

## Step 3 — Ingest the document {#step-3-ingest}

```bash
okfsmith ingest ./kb guide.md --no-llm
```

```text
              Ingest summary — sectioning (no LLM)
┏━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━┓
┃ File     ┃ SHA-256      ┃ Concepts ┃ Status ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━┩
│ guide.md │ 00902a6ea326 │        5 │ ok     │
└──────────┴──────────────┴──────────┴────────┘
ingested 5 concept(s) from 1 file(s) into kb
```

The `--no-llm` flag splits the document on its headings — one concept
per section. No model is called, so nothing leaves your machine.

Let's see what landed in the bundle:

```bash
okfsmith list ./kb
```

```text
                                 Concepts in kb
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ ID                                  ┃ Type  ┃ Title             ┃ Trust tier ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ guide/getting-started-with-okfsmith │ Draft │ Getting started   │ unverified │
│                                     │       │ with okfsmith     │            │
│ guide/installation                  │ Draft │ Installation      │ unverified │
│ guide/trust-tiers                   │ Draft │ Trust tiers       │ unverified │
│ guide/validation                    │ Draft │ Validation        │ unverified │
│ guide/your-first-bundle             │ Draft │ Your first bundle │ unverified │
└─────────────────────────────────────┴───────┴───────────────────┴────────────┘
5 concept(s)
```

Concept IDs are `file-slug/heading-slug`. Read any concept in full:

```bash
okfsmith read ./kb guide/trust-tiers
```

```text
---
type: Draft
title: Trust tiers
description: Draft concept extracted without LLM; needs review
resource: guide.md
generated:
  by: okfsmith/0.2.0
  at: '2026-09-26T12:19:30.999358+00:00'
status: draft
tags:
- draft
- no-llm
---
Every concept carries a trust tier: `unverified`, `machine-confirmed`,
or `human-reviewed`. No-LLM ingests land at `unverified`, which tells
every reader exactly how much trust to place in the content. Promote
tiers as concepts get reviewed and confirmed.
```

> [!NOTE]
> Ingesting the same file twice is safe — okfsmith tracks each file's
> SHA-256 hash and skips files it has already ingested.

## Step 4 — Validate the bundle {#step-4-validate}

```bash
okfsmith validate ./kb
```

```text
       Errors (0)
┏━━━━━━┳━━━━━━┳━━━━━━━━━┓
┃ Code ┃ File ┃ Message ┃
┡━━━━━━╇━━━━━━╇━━━━━━━━━┩
└──────┴──────┴─────────┘
      Warnings (0)
┏━━━━━━┳━━━━━━┳━━━━━━━━━┓
┃ Code ┃ File ┃ Message ┃
┡━━━━━━╇━━━━━━╇━━━━━━━━━┩
└──────┴──────┴─────────┘
Conformant: no errors, no warnings.
```

Validation checks the bundle against OKF v0.2 — error codes E001–E004
and warning codes W001–W015. Zero errors and zero warnings means the
bundle is conformant (it also exits with code `0`, so you can use it in
scripts). Curious what the rules check? See
[Validation & error codes](validation.html).

## Step 5 — Look at the concept graph {#step-5-graph}

```bash
okfsmith graph ./kb
```

```text
5 concept(s), 0 link(s), 0 dead link(s).

Orphans (0):
  (none)

Dead links (0):
  (none)
```

Deterministic sectioning produces standalone concepts, so a fresh
`--no-llm` bundle has no links between concepts yet — that's normal.
For a picture instead of text, generate the interactive viewer:

```bash
okfsmith graph ./kb --format html
```

This writes `kb/viz.html` — open it in any browser. It works fully
offline: search, backlinks, and a colorblind-safe trust-tier legend.
All viewer features are covered in
[Visualizing the knowledge graph](graph.html).

## You did it {#done}

In five minutes you went from an empty folder to a validated, visual
knowledge bundle — with no API key and no cloud service involved.

<details><summary>Advanced</summary>

**Ingest a whole folder:**

```bash
okfsmith ingest ./kb ./docs --no-llm --recursive
```

**Preview without writing anything:**

```bash
okfsmith ingest ./kb guide.md --no-llm --dry-run
```

**Quieter output** (only warnings, errors, and the final summary):

```bash
okfsmith ingest ./kb guide.md --no-llm --quiet
```

**Machine-readable output** for scripts:

```bash
okfsmith validate ./kb --format json
okfsmith list ./kb --format json
```

</details>

---

**Next: [Interactive chat →](chat.html)** — ask your bundle questions in
natural language, right in your terminal.
