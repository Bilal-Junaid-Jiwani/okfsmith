---
title: FAQ
eyebrow: User guide
description: Short answers to the most common beginner questions: cost, API keys, supported files, privacy, Python versions, trust tiers, and where to get help.
---

## What is okfsmith, and what is an OKF bundle? {#what-is-okfsmith}

okfsmith is a command-line tool that turns messy documentation — Markdown
files, PDFs, Office docs, whole folders — into a **knowledge bundle**
following the Open Knowledge Format (OKF).

A bundle is deliberately boring technology: a folder of Markdown files
with machine-readable frontmatter (type, title, trust tier, source).
Humans can read it with any text editor; agents can consume it over
[MCP](mcp.html) or in the [interactive chat](chat.html). Nothing
proprietary, nothing locked in.

## Does okfsmith cost anything? {#cost}

No. okfsmith is free and open-source (Apache-2.0) and local-first. The
default `--no-llm` workflow needs no account, no subscription, and no
API key. If you later choose LLM-powered extraction or generative chat
answers, you pay whatever your own model provider charges — okfsmith
itself adds no fee.

## Do I need an API key or an LLM to use it? {#api-key}

No. Everything in the [Quickstart](quickstart.html) works with
`--no-llm`, which uses deterministic sectioning instead of a model.
Concepts created this way are marked `unverified` so readers know how
they were made.

An API key only becomes relevant when you want richer behavior:

- **LLM extraction:** run `ingest` *without* `--no-llm` to have a model
  pull out concepts, links, and summaries instead of splitting on
  headings.
- **Generative chat:** `chat` without `--no-llm` answers in natural
  language instead of keyword-matched excerpts.

Both work with any of the 15 OpenAI-compatible provider presets — see
[Providers & API keys](providers.html).

> [!WARNING]
> `ingest` without `--no-llm` calls an LLM by default. If no LLM is
> reachable it **errors** — it does not silently fall back to
> deterministic sectioning.

## Which file types can I ingest? {#file-types}

Out of the box: **Markdown** (and plain text) via the built-in
LiteParse parser. With optional extras:

| Extra | Unlocks |
|---|---|
| `pip install "okfsmith[office]"` | Word, Excel, PowerPoint via MarkItDown |
| `pip install "okfsmith[ocr]"` | Scanned PDFs and images via OCR |

You can also point `ingest` at PDFs, Notion exports, zip archives, and
whole directories (`--recursive`). The full breakdown of parser tiers is
in [Ingesting documents](ingesting.html).

## Does my data leave my computer? {#privacy}

Not unless you ask it to. In `--no-llm` / extractive mode every byte
stays local — there is no telemetry and no cloud call. Your documents
only travel to a third party when you explicitly configure a hosted
provider (via `OKFSMITH_API_KEY` or `--provider`) for LLM extraction or
generative chat. Even then, `okfsmith doctor` reports key status as
`set (hidden)` — it never prints your keys.

## Which Python versions are supported? {#python-versions}

Python **3.10 or newer** (3.10, 3.11, 3.12, 3.13). Check yours with
`python --version`; installation help is on the
[Installation](install.html) page.

## Will okfsmith change or delete my original documents? {#safe}

No. `ingest` only *reads* your source files — it copies content into
the bundle and never modifies the originals. There is also no CLI
command that deletes, renames, or edits concepts; the bundle only grows
by ingestion. The chat REPL even says goodbye with
`Goodbye — your bundle is untouched`.

Re-ingesting the same file is safe too: okfsmith tracks each file's
SHA-256 hash and skips files it has already ingested.

## What do "Draft" and "unverified" mean? {#trust-tiers}

Every concept carries two honesty labels:

- **Type `Draft`** — the concept came from automated extraction and has
  not been curated yet.
- **Trust tier `unverified`** — nobody (human or machine) has confirmed
  the content yet. Other tiers are `machine-confirmed` and
  `human-reviewed`.

These labels are the point: a reader (or an agent) can see at a glance
exactly how much trust to place in each concept, instead of guessing.

## Why was my file skipped during ingest? {#why-skipped}

If you see `skipped (below 1000-char minimum; stub prevention)`, the
file was under ~1,000 characters. In `--no-llm` mode tiny files produce
meaningless one-line "concepts", so okfsmith refuses to ingest them
rather than polluting your bundle with stubs. Combine small notes into a
larger document, or use LLM extraction for short files.

## Where do I go when something breaks? {#help}

1. Run `okfsmith doctor` — it pinpoints missing extras, unreachable
   Ollama, and key configuration.
2. Check [Troubleshooting](troubleshooting.html) for the common errors
   (`slice-not-installed`, `llm-unavailable`, `not-a-bundle`, and more).
3. If it's still broken, file an issue on GitHub with the `doctor`
   output attached:
   [github.com/Bilal-Junaid-Jiwani/okfsmith/issues](https://github.com/Bilal-Junaid-Jiwani/okfsmith/issues).
