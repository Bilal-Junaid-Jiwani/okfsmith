---
title: Troubleshooting
eyebrow: Troubleshooting
description: Fix every common okfsmith failure — start with okfsmith doctor, then match your error to its fix.
---

## Troubleshooting

Something broken? **Run `okfsmith doctor` first.** It checks your Python,
dependencies, optional extras, Ollama reachability, LLM provider/key status,
and tmp writability in one table — most problems reveal themselves there.

```bash
okfsmith doctor
```

Then find your symptom in the table below.

## Common errors and fixes

| Symptom | Fix |
|---|---|
| `command not found: okfsmith` | It's not on your PATH. Reinstall with `pip install okfsmith` (or check `pipx`/`uvx` shims), then open a new terminal. See [Installation](install.html). |
| `okfsmith mcp ./kb` → `error [missing-extra]` | Install the MCP extra: `pip install "okfsmith[mcp]"`. `doctor` flags this row as `MISSING` when it's absent. |
| `ingest` fails: LLM unreachable / connection refused | No LLM is reachable and LLM extraction is the default. Either start Ollama (`ollama serve`), set `OKFSMITH_API_KEY` + `OKFSMITH_PROVIDER` (see [Providers](providers.html)), or run with `--no-llm`. |
| `ollama` row shows `WARN: not reachable` | Ollama isn't running. Start it (`ollama serve`) or use `--no-llm`. This is a warning, not a failure — `--no-llm` mode works fine without it. |
| Small files ingest as "skipped (below 1000-char minimum; stub prevention)" | Expected. In `--no-llm` mode, files under ~1000 characters are skipped to prevent stub concepts. Add more content or ingest a larger file. |
| `okfsmith search ...` → `No such command` | `search` is not a CLI command. Inside `chat`, use the `/search` slash command; over MCP, use the `search` tool; on the CLI, list concepts with `okfsmith list` and read one with `okfsmith read`. See [search and get](cli.html#search-and-get). |
| `okfsmith get ...` → `No such command` (suggests `ingest`) | `get` is not a CLI command — it's an MCP tool. The CLI equivalent is `okfsmith read ./kb <concept-id>`. |
| `doctor` shows `set (hidden)` instead of my key | That's the fix working: keys are never echoed. `set (hidden)` means your key **was** detected (with its source, e.g. `via OKFSMITH_API_KEY`). |
| `--model` + `--no-llm` → parameter error | `--no-llm` does deterministic extraction and never calls a model, so the combination is rejected. Drop `--model`. |
| `validate` reports E001–E004 errors | Hard conformance failures — the bundle isn't OKF v0.2 conformant. See [Validation](validation.html) for what each code means. |
| `validate` reports W001–W015 warnings | Advisory lints. The bundle is conformant; add `--strict` to treat warnings as failures. See [Validation](validation.html). |
| `graph` shows 0 links / 0 orphans | Normal for a fresh `--no-llm` bundle: deterministic sectioning produces no inter-concept links. LLM extraction adds links. |
| `mcp` / `chat` says a bundle id "not found" | You're pointing at a directory that isn't a bundle (missing `index.md`/`log.md`). Run `okfsmith init <dir>` first, or check the path. |
| Re-ingesting produces nothing new | Ingest deduplicates by per-file SHA-256 (manifest-tracked). Already-ingested files are skipped — edit the file or use `--force` where available. |

## Zero-concept ingests

If `ingest` finishes but `list` shows nothing:

1. Check the ingest summary table — files may be **skipped** (too small,
   already ingested, or unparseable).
2. Confirm the source path actually contains files (`--recursive` helps with
   directories).
3. Verify with `okfsmith doctor` that parsing dependencies are present.

## Still stuck?

1. Re-run `okfsmith doctor` and read the `Status` column top to bottom.
2. Check whether the problem is [fixed in a newer version](changelog.html).
3. File an issue on the okfsmith repo — include the **full** `doctor` table
   output (keys are masked, so it's safe to paste) plus the exact command and
   error text.

> [!NOTE]
> Never paste an actual API key into an issue or chat message — keep keys in
> environment variables only (see [Providers](providers.html)).

## Next →

[Changelog →](changelog.html)
