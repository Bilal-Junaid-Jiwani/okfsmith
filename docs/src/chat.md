---
title: Interactive chat
eyebrow: Getting started
description: Ask questions over your knowledge bundle in the Claude-Code-style REPL — with citations, slash commands, and an extractive mode that needs no API key.
---

## Start chatting in 10 seconds

`okfsmith chat` opens a REPL (an interactive prompt — you type, it answers) where you ask natural-language questions over your bundle. With `--no-llm` it works with zero setup — no API keys, no local model:

```bash
okfsmith chat ./kb --no-llm
```

The bundle argument is optional — if your current directory *is* a bundle, run `okfsmith chat`.

## The startup screen

Here is the real startup banner — the command, then exactly what prints
(the version line shows your installed version):

```bash
okfsmith chat ./kb --no-llm
```

```text
 ███  █   █ █████  ████ █   █ █████ █████ █   █
█   █ █  █  █     █     ██ ██   █     █   █   █
█   █ ███   ████   ███  █ █ █   █     █   █████
█   █ █  █  █         █ █   █   █     █   █   █
 ███  █   █ █     ████  █   █ █████   █   █   █
okfsmith chat v0.3.0
Bundle: kb (18 concepts) · extractive mode
Extractive mode — no LLM reachable. Answers are keyword-matched excerpts. Start
Ollama, set OKFSMITH_API_KEY + OKFSMITH_PROVIDER, or pass --provider, for
generative answers.

Tips for getting started:
  1. Ask questions about your documents.
  2. Type /help for chat commands.
  3. Type /ingest <path> to add more documents.

kb ›
```

What you're looking at:

- **ASCII logo** — the block-letter "OKF" banner prints first.
- **Version line** — `okfsmith chat v0.3.0`, your installed version.
- **Bundle info line** — `Bundle: kb (18 concepts) · extractive mode`: bundle name, concept count, and which answer mode is active.
- **Mode explainer** — in extractive mode you get two lines telling you exactly how to upgrade to generative answers (start Ollama, set `OKFSMITH_API_KEY` + `OKFSMITH_PROVIDER`, or pass `--provider`).
- **Three tips** — what to do next.
- **Prompt** — `kb › `: bundle name plus `› `.

> [!TIP]
> For generative (LLM) answers, either start Ollama locally or pass a hosted provider: `okfsmith chat ./kb --provider openrouter --model anthropic/claude-sonnet-4`. Set your key as an env var — never as a flag: `export OKFSMITH_API_KEY=your-key-here`. See [Providers](providers.html).

## Asking questions

Start typing. Plain English goes to the question-answer path; lines starting with `/` are slash commands:

```text
kb › what is the 1000-char rule?
kb › /help
kb › /search trust tiers
```

> [!NOTE]
> There is **no `okfsmith search` CLI command**. Search inside chat is the `/search` slash command (keyword search over concepts). The same `search` exists as an MCP tool on the server — see [MCP server](mcp.html). The CLI equivalent of `get` is `read`, mirrored by `/read` here.

## Extractive vs generative answers

Chat has two answer modes, shown on the bundle info line:

| | Extractive mode | Generative mode |
|---|---|---|
| Activated by | `--no-llm`, or no LLM reachable | Default when an LLM is reachable |
| How answers are built | Keyword-matched excerpts from your concepts | LLM composes an answer over retrieved context |
| Needs | Nothing — fully offline | Ollama running, or `--provider` + `OKFSMITH_API_KEY` |
| Citations | Match table shows concept IDs | Answers cite concepts as `[concept-id]` |

Extractive answers look like this:

```
✦ Matches for: trust tiers
┏━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Concept           ┃ Trust tier ┃ Excerpt                   ┃
┡━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ big/trust-tiers   │ unverified │ ...three trust tiers...   │
└───────────────────┴────────────┴───────────────────────────┘
Extractive mode: excerpts above, no generative summary. Use /read <id> for the full concept.
```

- In **generative mode**, answers cite their sources inline as `[concept-id]` — e.g. `The 1000-char rule [big/stub-prevention] prevents stub concepts.` — so you can verify any claim with `/read <id>`.
- In **extractive mode** you get the excerpt table instead of a summary; use `/read big/trust-tiers` to see the full concept.

> [!WARNING]
> `--model` cannot be combined with `--no-llm` — the CLI raises a parameter error. Pick one mode: extractive (`--no-llm`) or generative (`--provider`/`--model`).

## All slash commands

`/help` inside chat prints this table:

| Command | What it does |
|---|---|
| `/help` | Show this table. |
| `/ingest <path> [--recursive]` | Ingest a file or directory into the bundle. |
| `/list` | List concepts in the bundle. |
| `/read <id>` | Print a concept in full. |
| `/search <keywords>` | Keyword-search concepts. |
| `/validate` | Validate the bundle against OKF v0.2. |
| `/graph` | Show the concept link graph. |
| `/doctor` | Check the environment. |
| `/model` | Show or switch the LLM backend/model/provider. |
| `/clear` | Clear the screen and conversation history. |
| `/exit` | Leave the chat (`/quit` works too). |

Example session:

```text
kb › /list
                      Concepts in kb
┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ ID                 ┃ Type  ┃ Title        ┃ Trust tier ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ big/first-bundle   │ Draft │ First Bundle │ unverified │
│ big/installation   │ Draft │ Installation │ unverified │
└────────────────────┴───────┴────────────┴────────────┘
18 concept(s)
kb › /read big/first-bundle
---
type: Draft
title: First Bundle
...
kb › /exit
Goodbye — your bundle is untouched.
```

## History, quitting, and keys

- **Command history** is kept at `~/.okfsmith/history` — it's loaded when chat starts and saved on exit, so your up-arrow recalls previous sessions too.
- **Ctrl-D** (EOF) exits the chat.
- **Ctrl-C** cancels the current input line — the session survives: `Input cancelled — type /exit to quit.`
- **`/exit` or `/quit`** leaves the chat with `Goodbye — your bundle is untouched.`
- Chat **never modifies your bundle** — reading is read-only by design.

> [!TIP]
> Chat works non-interactively over piped stdin too: `printf '/list\n/exit\n' | okfsmith chat ./kb --no-llm`. Handy for scripting.

<details>
<summary>Advanced</summary>

- `--provider <str>` — hosted provider preset for generative answers (see [Providers](providers.html)).
- `--model <str>` — model id for generative answers; overridden per-session with `/model`.
- `/ingest <path> [--recursive]` inside chat takes the same sources as the `ingest` command; files below the 1000-char minimum are skipped in `--no-llm` mode (see [Ingesting documents](ingesting.html)).
- `/doctor`, `/validate`, `/graph` mirror the CLI commands of the same names.

</details>

---

**Next: [Ingesting documents →](ingesting.html)** — how documents become concepts in the first place.
