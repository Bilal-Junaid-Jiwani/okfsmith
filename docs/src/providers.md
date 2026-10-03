---
title: Providers & API keys
eyebrow: Providers
description: Use any hosted model with okfsmith — 16 provider presets (including Anthropic's native API), API keys via environment variables, local Ollama by default.
---

## Providers & API keys

okfsmith's LLM mode (`ingest` extraction, `chat` generative answers) works with
**any OpenAI-compatible endpoint — plus Anthropic's native API**. Out of the
box, the default is local and free: **Ollama**. When you're ready for hosted
models, pick one of the 16 presets and add an API key.

> [!NOTE]
> Don't have an LLM available? You can skip this page entirely. `ingest --no-llm`
> and `chat --no-llm` work with zero setup — see `quickstart.html`.

## Quick setup: a hosted provider in 60 seconds

```bash
export OKFSMITH_PROVIDER=openrouter
export OKFSMITH_API_KEY=your-key-here
export OKFSMITH_MODEL=openai/gpt-4o-mini

okfsmith chat ./kb
```

That's it. Verify your key is detected (without ever seeing the key) with:

```bash
okfsmith doctor
```

## The 16 provider presets

`--provider` accepts any of these. All but one map to the provider's
OpenAI-compatible base URL; `anthropic` speaks Anthropic's native Messages
API instead (no proxy needed):

| Preset | What it's for |
|---|---|
| `ollama` | Local models via Ollama — the default, free, private |
| `lmstudio` | Local models via LM Studio |
| `openai` | OpenAI's API (GPT models) |
| `groq` | Groq's fast inference API |
| `mistral` | Mistral AI's API |
| `deepseek` | DeepSeek's API |
| `openrouter` | OpenRouter — one key, hundreds of models |
| `together` | Together AI inference |
| `fireworks` | Fireworks AI inference |
| `deepinfra` | DeepInfra inference |
| `anyscale` | Anyscale endpoints |
| `perplexity` | Perplexity's API |
| `xai` | xAI's API (Grok) |
| `gemini` | Google's Gemini via its OpenAI-compatible endpoint |
| `agentrouter` | Agent Router — gateway to many providers |
| `anthropic` | Anthropic's **native** Messages API (Claude models, no proxy) |

```bash
# Same command, any provider — change only the preset
okfsmith ingest ./kb report.pdf --provider groq --model llama-3.3-70b-versatile
```

## Environment variables

| Variable | Purpose |
|---|---|
| `OKFSMITH_API_KEY` | API key for the hosted endpoint **(preferred)** |
| `OKFSMITH_PROVIDER` | Provider preset name (e.g. `openrouter`) |
| `OKFSMITH_API_BASE` | Custom OpenAI-compatible base URL (see below) |
| `OKFSMITH_MODEL` | Default model name (overridden by `--model`) |
| `AGENTROUTER_API_KEY` | Honored when the provider resolves to `agentrouter` |
| `ANTHROPIC_API_KEY` | Honored when the provider resolves to `anthropic`; with no provider or base configured, selects the native Anthropic backend automatically |
| `OPENAI_API_KEY` | Legacy fallback for hosted OpenAI-compatible endpoints |

### Example: Agent Router

```bash
export OKFSMITH_PROVIDER=agentrouter
export AGENTROUTER_API_KEY=your-key-here
okfsmith chat ./kb --model anthropic/claude-sonnet-4
```

> [!TIP]
> Set the variables in your shell profile (`~/.bashrc`, `~/.zshrc`) so they
> persist between sessions — or use a `.env` file with a tool like `direnv`.
> Keep the key out of your shell history.

## Flags

| Flag | What it does |
|---|---|
| `--provider <name>` | Choose a preset (e.g. `openrouter`) |
| `--model <id>` | Model id for extraction/chat answers |
| `--api-base <url>` | **Any other** OpenAI-compatible endpoint — overrides `--provider` |
| `--api-key <key>` | Pass a key directly ⚠️ warns: this lands in your shell history |

### Example: anything else via `--api-base`

Azure OpenAI, self-hosted vLLM or llama.cpp, any compat proxy — all work:

```bash
# keep the key in an env var — never as a flag (flags land in shell history)
export OKFSMITH_API_KEY=your-key-here
okfsmith ingest ./kb docs/ --api-base https://my-proxy.example.com/v1 \
  --model my-model
```

## Precedence order

When several sources are set, okfsmith resolves them in this order:

1. **Flags** — `--provider`, `--model`, `--api-base`, `--api-key`
2. **Environment variables** — `OKFSMITH_PROVIDER`, `OKFSMITH_MODEL`, `OKFSMITH_API_BASE`, `OKFSMITH_API_KEY`
3. **Implied provider** — `ANTHROPIC_API_KEY` alone (no provider or base configured) selects native `anthropic`
4. **Defaults** — Ollama at `http://localhost:11434/v1`, model `qwen3:8b`

So a flag always wins over an env var, which wins over the built-in default.

## Ollama: the local default

With no keys and no flags, okfsmith expects Ollama on your machine:

```bash
# 1. Install Ollama from https://ollama.com, then pull a model
ollama pull qwen3:8b

# 2. Use okfsmith as-is — no keys, no env vars
okfsmith ingest ./kb report.pdf
```

`doctor` reports the Ollama reachability, provider, base URL, and model it's
using — handy when something feels off (`cli.html#okfsmith-doctor`).

> [!WARNING]
> `okfsmith doctor` never prints your key. The key row shows `set (hidden)`
> plus the source, e.g. `set (hidden) (via OKFSMITH_API_KEY)`. If you only see
> `set (hidden)` and expected your actual key to be shown — that's by design,
> and it's working correctly.

## Anthropic's native API

Anthropic's own API is **not** OpenAI-compatible — so instead of a proxy,
okfsmith speaks it directly with `--provider anthropic` (native Messages
API, default model `claude-haiku-4-5`):

```bash
export ANTHROPIC_API_KEY=your-key-here
okfsmith chat ./kb --provider anthropic
# ...or with no provider configured at all: ANTHROPIC_API_KEY alone
# selects the native backend automatically
okfsmith ingest ./kb docs/
```

Claude models are still reachable through the OpenAI-compatible gateways
too (`openrouter`, `agentrouter`) — same commands as before:

```bash
# Option 1: OpenRouter
export OKFSMITH_PROVIDER=openrouter
export OKFSMITH_API_KEY=your-key-here
okfsmith chat ./kb --model anthropic/claude-sonnet-4

# Option 2: Agent Router
export OKFSMITH_PROVIDER=agentrouter
export AGENTROUTER_API_KEY=your-key-here
```

> [!NOTE]
> More detail on supported models and the Ollama vs hosted trade-off lives in
> `faq.html`.

<details>
<summary>Advanced: how keys are resolved and masked</summary>

- `doctor` distinguishes the key's source: `via OKFSMITH_API_KEY`,
  `via AGENTROUTER_API_KEY`, `via ANTHROPIC_API_KEY`, or
  `via OPENAI_API_KEY`. The value is never
  echoed, logged, or included in JSON output.
- The CLI's own `--help` for `--api-key` explicitly warns that the flag value
  lands in shell history — prefer the env var.
- `OKFSMITH_API_BASE` (or its alias `OKFSMITH_BASE_URL`) accepts any
  OpenAI-compatible base URL; when set, it takes precedence over the preset's
  canonical URL (`--api-base` overrides both).
- Combining `--model` with `--no-llm` is a parameter error — `--no-llm` mode
  does deterministic extraction and never calls a model.
- LLM extraction is the default ingest path: running `ingest` *without*
  `--no-llm` calls the configured LLM, and if none is reachable it errors
  rather than silently falling back.

</details>

> [!WARNING]
> **Never put API keys in chat messages, issue reports, screenshots, or
> committed config files.** Keys belong in environment variables only. If a key
> leaks, rotate it at the provider's dashboard immediately.

## Next →

[CLI reference →](cli.html)
