<p align="center">
  <img src="docs/assets/img/logo.svg" width="96" height="96" alt="okfsmith logo — a blacksmith's anvil with a forge spark">
</p>

# okfsmith

[![PyPI](https://img.shields.io/pypi/v/okfsmith.svg)](https://pypi.org/project/okfsmith/)
[![Python](https://img.shields.io/pypi/pyversions/okfsmith.svg)](https://pypi.org/project/okfsmith/)
[![License](https://img.shields.io/github/license/Bilal-Junaid-Jiwani/okfsmith.svg)](https://github.com/Bilal-Junaid-Jiwani/okfsmith/blob/master/LICENSE)
[![Docs](https://img.shields.io/badge/docs-website-D97757)](https://bilal-junaid-jiwani.github.io/okfsmith/)

**Forge messy documents into [OKF v0.2](https://github.com/GoogleCloudPlatform/open-knowledge-format) knowledge bundles.**

okfsmith is a Python CLI that ingests PDFs, markdown, wiki dumps, and Notion
exports and emits spec-conformant OKF v0.2 bundles: markdown files with YAML
frontmatter, plus reserved `index.md` and `log.md`. Every concept carries
provenance (`sources[]`), a trust tier, and lifecycle metadata, and every
bundle is checked by a built-in §11 validator. Serve it to your agents with
one MCP command.

## 60-second quickstart

```bash
pip install okfsmith

okfsmith init ./kb
okfsmith ingest ./kb notes/ report.pdf --no-llm   # offline first pass
okfsmith validate ./kb
okfsmith graph ./kb --format html   # writes ./kb/viz.html — open in a browser
```

Point any MCP-capable agent at the bundle:

```bash
pip install "okfsmith[mcp]"
okfsmith mcp ./kb
```

Tools exposed: `index`, `list`, `search`, `get`, `neighbors` — every answer
traces back to `sources[]` in the bundle.

## Why okfsmith

Clean markdown already has good OKF tooling. The messy middle — 200-page PDFs
with broken reading order, sprawling Notion exports, wiki dumps — is where
knowledge usually lives, and that's what okfsmith ingests first:

**parse → section → extract → link → emit → validate → serve**

- **Tiered parsing, free first.** Tier 1 is local and keyless: LiteParse for
  PDFs, stdlib parsing for markdown/text. Office formats (`.docx`, `.pptx`,
  `.xlsx`) via the optional `okfsmith[office]` extra; Docling OCR sidecar via
  `okfsmith[ocr]` for scanned pages. PyMuPDF is deliberately avoided (AGPL).
- **Two extraction modes.** `--no-llm` writes one draft concept per section —
  fast, offline, deterministic. With an LLM (Ollama by default, or an
  OpenAI-compatible API via env vars), a draft + critic flow extracts claims
  with `[^source-id]` citations feeding `sources[]`.
- **OKF v0.2 native.** Only `type` is required in frontmatter. okfsmith also
  emits `sources[]`/provenance, `generated`/`verified` trust metadata, and
  lifecycle fields.
- **§11 validator.** The spec's hard conformance rules (E001–E004) plus
  advisory lints (dead links, orphans, stubs, legacy v0.1 fields). Broken
  links are warnings, never errors (spec §6).
- **Graph visualization.** `okfsmith graph --format html` renders a
  self-contained `viz.html` (works offline): nodes colored by type with a
  colorblind-safe palette, shaped by trust tier, with backlinks, search, and
  keyboard access.
- **One-command MCP server.** `okfsmith mcp ./kb` over stdio, SSE, or
  streamable HTTP.
- **Skill pack.** `skills/okfsmith-build/SKILL.md` teaches agents the
  init → ingest → validate → serve loop.

## CLI reference

| Command | What it does |
|---|---|
| `okfsmith init BUNDLE` | scaffold `index.md` + `log.md` |
| `okfsmith ingest BUNDLE SOURCE...` | parse, section, extract → draft concepts |
| `okfsmith validate BUNDLE` | check OKF §11 conformance (exit 0 = conformant) |
| `okfsmith list BUNDLE` | list concepts (filter by `--tier`, `--type`) |
| `okfsmith read BUNDLE ID` | print one concept |
| `okfsmith graph BUNDLE` | links: text / json / mermaid / html |
| `okfsmith search BUNDLE QUERY` | BM25 full-text search (flags: `--limit`/`-n`, `--format text\|json`, `--tier`, `--type`) |
| `okfsmith mcp BUNDLE` | serve over MCP |
| `okfsmith chat BUNDLE` | interactive Q&A over the bundle (REPL) |
| `okfsmith doctor` | check dependencies, extras, Ollama |

The bundle is always the first positional argument. Expected failures print
`error [CODE]:` with a hint and never a traceback; usage errors exit 2.

Full reference with examples: [docs/commands.md](docs/commands.md).

## Interactive chat

`okfsmith chat` opens a Claude Code / Gemini CLI style REPL over your bundle:
ask questions in plain language, get answers with `[concept-id]` citations.
With local Ollama running (or `OPENAI_API_KEY` set) answers are synthesized
and grounded; otherwise the chat stays useful in extractive mode, showing the
keyword-matched concepts themselves. It never answers from thin air — no
relevant concepts, no invented answer.

```text
$ okfsmith chat ./kb
 ███  █   █ █████  ████ █   █ █████ █████ █   █
█   █ █  █  █     █     ██ ██   █     █   █   █
█   █ ███   ████   ███  █ █ █   █     █   █████
█   █ █  █  █         █ █   █   █     █   █   █
 ███  █   █ █     ████  █   █ █████   █   █   █
okfsmith chat v0.3.0
Bundle: kb (24 concepts) · openai · qwen3:8b

Tips for getting started:
  1. Ask questions about your documents.
  2. Type /help for chat commands.
  3. Type /ingest <path> to add more documents.

kb › how do I authenticate?
✦
Use a Bearer token in the Authorization header [api/auth].

*Sources: [api/auth]*
kb › aur iska source kya hai
✦
The dashboard, under Settings › API Keys [api/auth].

*Sources: [api/auth]*
kb › /exit
Goodbye — your bundle is untouched.
```

(On a real terminal the logo renders as a yellow→orange→magenta gradient,
the prompt bundle name is colored, and answers carry a subtle `✦` marker.
Piped output stays plain ASCII — zero escape codes, always.)

Slash commands: `/help` `/ingest` `/list` `/read` `/search` `/validate`
`/graph` `/doctor` `/model` `/clear` `/exit`. Line history persists at
`~/.okfsmith/history`; Ctrl-C cancels input, Ctrl-D quits. Flags:
`--model` to pick the model, `--no-llm` to force extractive mode.

## Use any model (API key)

Ollama is the default, but any OpenAI-compatible model works — one key,
any provider. **OpenRouter** is the flagship: a single key routes to
hundreds of models (`anthropic/claude-sonnet-4`-style IDs included):

```bash
export OKFSMITH_API_KEY="sk-or-..."        # your OpenRouter key
okfsmith chat ./kb --provider openrouter --model anthropic/claude-sonnet-4
okfsmith ingest ./kb docs/ --provider openrouter --model openai/gpt-4o-mini
```

Prefer env vars — the flags also work:

```bash
export OKFSMITH_API_KEY="..."              # Groq example
export OKFSMITH_PROVIDER=groq
okfsmith chat ./kb --model llama-3.3-70b-versatile

okfsmith chat ./kb --provider deepseek --model deepseek-chat
okfsmith chat ./kb --provider gemini --model gemini-2.0-flash

export AGENTROUTER_API_KEY="..."       # Agent Router gateway example
okfsmith chat ./kb --provider agentrouter --model gpt-4o-mini
```

Provider presets (15): `openrouter` · `groq` · `mistral` · `deepseek` ·
`together` · `fireworks` · `deepinfra` · `anyscale` · `perplexity` · `xai` ·
`gemini` · `openai` · `agentrouter` · `lmstudio` · `ollama`.

Literally anything else — Azure OpenAI, self-hosted vLLM, a llama.cpp
server, any compat proxy — works via `--api-base`:

```bash
okfsmith chat ./kb --api-base https://my-proxy/v1 --model my-model
```

Notes:

- Put the key in `OKFSMITH_API_KEY` (`AGENTROUTER_API_KEY` is honored
  for the `agentrouter` preset). `--api-key` also works but lands in
  your shell history — okfsmith warns you once per session about that.
- Keys are never logged, never shown (banners and `okfsmith doctor` only
  say `set (hidden)`), and never written to disk.
- Anthropic's **native** API is not OpenAI-compatible, so it can't be
  called directly — use the `openrouter` preset (routes to Claude with one
  key) or point `--api-base` at an OpenAI-compatible gateway in front of
  Anthropic.
- `okfsmith doctor` shows the resolved provider, base URL, model, and key
  status without probing the network.

## Install options

```bash
pip install "okfsmith[office]"   # DOCX / PPTX / XLSX
pip install "okfsmith[mcp]"      # MCP server
pip install "okfsmith[ocr]"      # Docling OCR sidecar
pipx install "okfsmith[office,mcp]"
```

`okfsmith doctor` verifies your setup.

## Docs

📚 **Live documentation website:** <https://bilal-junaid-jiwani.github.io/okfsmith/>

[Documentation index](docs/index.md) · [Quickstart](docs/quickstart.md) ·
[Pipeline](docs/pipeline.md) · [Searching](docs/searching.md) ·
[Validation](docs/validation.md) ·
[MCP](docs/mcp.md) · [Troubleshooting](docs/troubleshooting.md) ·
[FAQ](docs/faq.md)

## License

Apache-2.0. See [LICENSE](LICENSE).
