# Troubleshooting

## `error [slice-not-installed]: ...`

An optional extra is missing. The hint tells you the exact fix, e.g.
`pip install "okfsmith[office]"`. If you installed with `pipx`/`uvx`, add the
extra there instead.

## `error [llm-unavailable]: ...`

No model endpoint is reachable. Either start Ollama (`ollama serve`), set
`OKFSMITH_MODEL` / `OPENAI_API_KEY`, or retry with `--no-llm`.

## `error [not-a-bundle]: ...`

The directory exists but has no `index.md`. Run `okfsmith init` there first,
or point at the right directory.

## `ingested 0 concept(s)` — but I expected concepts

Sources under 1,000 characters are skipped by design (stub prevention).
Check with `--dry-run` to see what would be created.

## `E001: no parseable YAML frontmatter block found`

The concept file's frontmatter is missing or malformed. It must start with
`---` on the first line, contain valid YAML with a `type` key, and end with
`---`.

## `W001: broken link target`

A markdown link points at a concept id that doesn't exist in the bundle.
Either create the target concept or fix the link. `okfsmith graph` shows
dead links as red dashed edges.

## `W002: concept not reachable from any index.md entry`

The concept exists but isn't linked from the index. Add it to `index.md`
(or link to it from another concept) if it should be discoverable.

## The HTML graph is empty

The bundle has no concepts — the viewer shows a "Nothing to visualize yet"
card. Ingest something first, then re-render with
`okfsmith graph ./kb --format html`.

## Still stuck?

Run `okfsmith doctor` and include its output when asking for help. File
issues at <https://github.com/Bilal-Junaid-Jiwani/okfsmith/issues>.
