# LLM & no-LLM modes

`okfsmith ingest` has two extraction modes. Both write the same bundle
format; they differ in how much understanding is applied per section.

## `--no-llm` (default for quick passes)

One draft concept per section, no model calls, fully offline. Fast and
deterministic. Drafts get `trust: unverified` and a description noting they
need review. Sources under 1,000 characters are skipped ("stub prevention") —
tiny fragments make poor concepts.

## LLM mode

Without `--no-llm`, okfsmith extracts with a two-pass draft + critic flow:
claims are written with `[^source-id]` citations that resolve against
`sources[]` provenance.

### Model resolution order

1. `--model NAME` on the command line
2. `OKFSMITH_MODEL` environment variable
3. built-in default (Ollama)

### Backends

- **Ollama** (default): expects a server at `http://localhost:11434`
  (`ollama serve`). Fully local.
- **OpenAI-compatible**: set `OPENAI_API_KEY` (read from the environment
  only — never from files) and optionally `OKFSMITH_BASE_URL`.

If no endpoint is reachable, ingest fails cleanly with
`error [llm-unavailable]:` and a hint (`ollama serve`, env vars, or retry
with `--no-llm`) — never a traceback, never a leaked key. API keys are
redacted from logs and error output.

`--model` combined with `--no-llm` is a usage error (exit 2).

## Trust tiers, again

- LLM drafts start at `unverified` too. Promotion to `human-reviewed` is a
  human decision: edit the frontmatter (or use the `human_review` helper),
  then `okfsmith validate` to confirm the bundle still conforms.
