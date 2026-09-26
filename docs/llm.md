# LLM & no-LLM modes

`okfsmith ingest` has two extraction modes. Both write the same bundle
format; they differ in how much understanding is applied per section.

## `--no-llm` (default for quick passes)

One draft concept per section, no model calls, fully offline. Fast and
deterministic. Drafts carry no `verified` entry, so their trust tier derives
to `unverified` (trust is derived from `verified`, never a literal `trust:`
field). Sources under 1,000 characters are skipped ("stub prevention") —
tiny fragments make poor concepts.

## LLM mode

Without `--no-llm`, okfsmith extracts with a two-pass draft + critic flow:
claims are written with `[^source-id]` citations that resolve against
`sources[]` provenance.

### Model resolution order

1. `--model NAME` on the command line
2. `OKFSMITH_MODEL` environment variable
3. built-in default (Ollama `qwen3:8b`)

### Backends

- **Ollama** (default): expects a server at `http://localhost:11434`
  (`ollama serve`). Fully local. `okfsmith doctor` still reports whether
  it is reachable.
- **Provider presets** (`--provider NAME` or `OKFSMITH_PROVIDER`): 15
  OpenAI-compatible endpoints — `openrouter`, `groq`, `mistral`,
  `deepseek`, `together`, `fireworks`, `deepinfra`, `anyscale`,
  `perplexity`, `xai`, `gemini`, `openai`, `agentrouter`, `lmstudio`,
  `ollama`. The key comes from `OKFSMITH_API_KEY` (preferred),
  `--api-key`, `AGENTROUTER_API_KEY` (honored when the provider is
  `agentrouter`), or legacy `OPENAI_API_KEY`. `openrouter` is the
  flagship: one key routes to hundreds of models via `vendor/model`-style
  IDs (e.g. `--model anthropic/claude-sonnet-4`).
- **Anything else** (`--api-base URL` or `OKFSMITH_API_BASE`): Azure
  OpenAI, self-hosted vLLM, a llama.cpp server, any compat proxy. The base
  is the full API base (e.g. `https://my-proxy/v1`); okfsmith appends
  `/chat/completions`. A bare host with no path gains `/v1` automatically
  (the old `OPENAI_BASE_URL` contract keeps working).

Full precedence: flags → `OKFSMITH_*` → legacy `OPENAI_API_KEY` /
`OPENAI_BASE_URL` (and the `OKFSMITH_BASE_URL` alias promised here
earlier) → provider preset → default Ollama.

Anthropic's **native** API is not OpenAI-compatible, so it cannot be
called directly. Use the `openrouter` preset (one key, routes to Claude
models) or point `--api-base` at an OpenAI-compatible gateway in front of
Anthropic.

If no endpoint is reachable, ingest fails cleanly with
`error [llm-unavailable]:` and a hint (`ollama serve`, env vars, or retry
with `--no-llm`) — never a traceback, never a leaked key. API keys are
redacted from logs and error output; banners, `/model`, and
`okfsmith doctor` only ever show `set (hidden)` / `not set`.

`--model` combined with `--no-llm` is a usage error (exit 2) — as are
`--provider`, `--api-base`, and `--api-key` with `--no-llm`. Passing
`--api-key` on the command line prints a one-time warning: it lands in
shell history, so `OKFSMITH_API_KEY` is preferred.

## Trust tiers, again

- LLM drafts start at `unverified` too. The critic pass can promote clean
  drafts to `machine-confirmed` by adding a non-`human:` `verified` entry.
  Promotion to `human-reviewed` is a human decision: edit the frontmatter
  (or use the `human_review` helper), then `okfsmith validate` to confirm
  the bundle still conforms.
