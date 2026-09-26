---
title: Installation
eyebrow: Getting started
description: Install okfsmith from PyPI, add optional extras for Office docs, MCP, and OCR, set up shell completion, and verify everything with okfsmith doctor.
---

## Open a terminal {#open-terminal}

Everything below runs in a terminal (a command line). If you have never
opened one:

- **macOS:** press `Cmd + Space`, type `Terminal`, press Enter.
- **Windows:** press the `Win` key, type `PowerShell` (or `Terminal`), press Enter.
- **Linux:** press `Ctrl + Alt + T`, or search for "Terminal" in your apps.

You will type commands after the prompt and press Enter. Nothing here can
harm your computer — installing a Python package and creating files in a
folder you choose.

## Check Python {#check-python}

okfsmith needs **Python 3.10 or newer**. Check yours:

```bash
python --version
```

If that says `command not found`, try `python3 --version` instead. On
Windows, `py --version` also works. If your version is older than 3.10
(or Python is missing entirely), install the latest Python from
[python.org/downloads](https://www.python.org/downloads/) and come back
here.

```text
Python 3.12.3
```

Any 3.10+ works — 3.11, 3.12, 3.13 are all fine.

## Install okfsmith {#install}

Install from PyPI (the standard Python package index) with one command:

```bash
pip install okfsmith
```

> [!TIP]
> If `pip` is not found, use `pip3 install okfsmith`. On Windows,
> `py -m pip install okfsmith` always works.

That's the whole install. No accounts, no API keys, no configuration
files — the default workflow runs entirely on your machine.

### Optional extras {#extras}

Extras unlock extra capabilities. Install any of them together with the
base package:

```bash
pip install "okfsmith[office]"   # Word/Excel/PowerPoint docs via MarkItDown
pip install "okfsmith[mcp]"      # serve bundles to AI agents over MCP
pip install "okfsmith[ocr]"      # text extraction from scanned PDFs/images
```

> [!NOTE]
> The quotes around `okfsmith[mcp]` matter on macOS and Linux (zsh/bash
> treat square brackets specially). On Windows PowerShell you can write
> the quotes too — they are harmless there. Wondering which extra you
> need? [Ingesting documents](ingesting.html) explains the parser tiers
> each extra powers.

You can combine extras: `pip install "okfsmith[office,mcp,ocr]"`.

## Verify the install {#verify}

Run these two commands. The first prints the installed version:

```bash
okfsmith --version
```

```text
okfsmith 0.3.0
```

The second checks your whole environment — dependencies, extras,
Ollama, and whether your API keys are configured:

```bash
okfsmith doctor
```

```text
                                okfsmith doctor
┏━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Check          ┃ Status  ┃ Detail                                       ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ python >= 3.10 │ OK      │ 3.12.3                                       │
│ okfsmith       │ OK      │ 0.3.0                                        │
│ ...            │ ...     │ ...                                          │
│ extra: mcp     │ MISSING │ Install the 'mcp' extra: pip install        │
│                │         │ 'okfsmith[mcp]' ...                          │
│ ollama         │ WARN    │ not reachable at http://localhost:11434 —    │
│                │         │ use --no-llm or set OPENAI_API_KEY           │
│ llm api key    │ MISSING │ not needed for local Ollama; set             │
│                │         │ OKFSMITH_API_KEY for hosted providers        │
│ tmp writable   │ OK      │ /tmp                                         │
└────────────────┴━━━━━━━━━┴━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┘
```

> [!NOTE]
> `doctor` never prints your keys — it only shows `set (hidden)` plus
> where the key came from. A `MISSING` or `WARN` here is usually fine:
> `MISSING` extras mean an optional feature is off, and the Ollama
> `WARN` only matters if you plan to use LLM features. The no-LLM
> workflow you are about to try needs none of it.

If `doctor` shows `OK` for Python and okfsmith, you are ready.

## Upgrade and uninstall {#upgrade-uninstall}

To get the newest version later:

```bash
pip install --upgrade okfsmith
```

To remove okfsmith completely:

```bash
pip uninstall okfsmith
```

<details><summary>Advanced</summary>

**Virtual environments.** If you manage Python projects with virtual
environments, install okfsmith inside one like any other package:

```bash
python -m venv .venv
source .venv/bin/activate   # macOS/Linux
# .venv\Scripts\activate    # Windows
pip install okfsmith
```

**Shell completion.** Tab-completion for commands and flags is available
via Typer's built-in support:

```bash
okfsmith --install-completion   # install completion for your shell
okfsmith --show-completion      # preview the completion script
```

Restart your shell after installing completion for it to take effect.

**Installing a specific version:**

```bash
pip install "okfsmith==0.3.0"
```

</details>

---

**Next: [Quickstart →](quickstart.html)** — build your first knowledge
bundle in under five minutes.
