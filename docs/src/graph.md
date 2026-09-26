---
title: Visualizing the knowledge graph
eyebrow: User guide
description: See how your concepts link together — okfsmith graph reports nodes, edges, orphans and dead links, and can render an interactive HTML viewer.
---

## See the graph

```bash
okfsmith graph ./kb
```

Real output for a fresh `--no-llm` bundle:

```
18 concept(s), 0 link(s), 0 dead link(s).

Orphans (0):
  (none)

Dead links (0):
  (none)
```

What each number means:

- **concepts** — nodes in the graph (one per concept file).
- **links** — edges: a concept's body links to another concept in the bundle.
- **dead links** — link targets that resolve to no file (matches `W001` from [Validation](validation.html)).

A freshly ingested `--no-llm` bundle has 0 links — deterministic sectioning doesn't create inter-concept links, so every concept is standalone. That's normal, and it still validates.

## Orphans and dead links

- **Orphans** — concepts nothing links *to*. They're valid but isolated: readers can only reach them via `list` or search.
- **Dead links** — links pointing at targets that don't exist in the bundle (typos in hand-written links, renamed concept files).

To fix them:

1. Run `okfsmith graph ./kb` to list the offenders.
2. For dead links: open the source concept and correct the link target (or create the missing concept).
3. For orphans: link to them from related concepts, or add them to an `index.md` entry — note that `index.md`-reachability is what [validation rule W002](validation.html) checks.

> [!TIP]
> Links between concepts are the edges that turn a pile of drafts into a *knowledge graph*. When you write concept bodies by hand, link freely — `graph` will tell you when a target is wrong.

## Output formats

`graph` renders four ways:

| `--format` | Output |
|---|---|
| `text` (default) | The summary above, printed to stdout |
| `json` | Machine-readable: nodes, edges, orphans, dead links |
| `mermaid` | `flowchart LR` — one node per concept, e.g. `big_first_bundle["big/first-bundle — First Bundle"]`. Paste it into any Mermaid renderer. |
| `html` | An interactive visualization written to `<bundle>/viz.html` |

```bash
# write a Mermaid diagram to a file
okfsmith graph ./kb --format mermaid --output graph.mmd

# render the interactive viewer (offline: colorblind-safe palette, backlinks, search)
okfsmith graph ./kb --format html
```

The HTML viewer needs no server — open `kb/viz.html` in a browser. It shows the graph with a colorblind-safe palette, per-concept backlinks, a search box, and keyboard access. (Chat's `/graph` runs the same command inside the REPL.)

<details>
<summary>Advanced</summary>

- `--output <path>` writes to a file instead of stdout for any `--format` — combine with `--format html` to place the viewer somewhere specific: `okfsmith graph ./kb --format html --output ./site/viz.html`.
- JSON shape is `{"nodes": [...], "adjacency": {"<id>": ["<id>", ...]}, "dead_links": [...]}` — stable for scripting and CI checks.
- The default HTML output is always `<bundle>/viz.html`; pass `--output` to change it.
- Link analysis also runs inside `validate` (E001–E004/W001–W015), but `graph` is the tool for *exploring* the graph, not only conformance-checking it.

</details>

---

**Next: [Agent skill pack →](skill.html)** — teach agents the init → ingest → validate → serve workflow.
