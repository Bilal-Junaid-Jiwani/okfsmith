# UX Panel D — viz.html graph experience review

**Date:** 2026-09-26 · **Reviewers:** Panel D (3 senior data-viz/interaction designers, one voice)
**Scope:** `viz.html` produced by `okfsmith.viz.render_html` (branch `feat/viz`, commit `7b551c5`)
**Method:** Generated `viz.html` for `examples/bundles/cs-curriculum` (7 concepts) plus three
synthetic bundles — empty (0), deadlink (3 concepts, 1 dead link), large (600 concepts, 1791 links).
Audited via headless-Chromium screenshots, static code review of the embedded JS/CSS, WCAG contrast
measurement, and Node-based timing of the layout physics. Compared against Obsidian graph view,
Gephi, and Kumu.

## 1. VERDICT: **CHANGES-REQUIRED**

The renderer has a solid foundation (offline single file, trust-tier shapes, dead-link ghosts,
degree-scaled nodes, zoom-to-cursor), but it ships with a **ship-blocking bug that breaks all mouse
interaction**, a **legend that contradicts the canvas encoding**, and **no keyboard path into the
graph**. Best-in-class or nothing — this does not clear the bar yet.

## 2. Findings

| # | Severity | Area | Issue | Concrete fix spec |
|---|----------|------|-------|-------------------|
| 1 | **Critical** | Empty state / input | The "Nothing to visualize yet" overlay renders on **every** bundle, including populated ones (verified on 7- and 600-concept renders). Root cause: `#empty { display: flex; … }` in author CSS overrides the UA `[hidden] { display: none }` rule, so the `hidden` attribute is dead. Worse, `#empty` is `position:absolute; inset:0` and last in DOM order, so it sits **on top of the canvas and swallows every pointer event** — node click-to-select, node drag, pan, and even the detail panel's close button are unreachable by mouse. First impression is a false "nothing here" card. | CSS: replace `#empty { … display:flex … }` with `#empty { display:none; }` + `#empty:not([hidden]) { display:flex; align-items:center; justify-content:center; text-align:center; padding:24px; }`. Alternatively `#empty[hidden]{display:none !important}`. Add a regression test: render a non-empty bundle, assert `#empty` is not visible / has no pointer interception (e.g. `getComputedStyle(...).display === 'none'`). |
| 2 | **High** | Legend legibility | Legend trust swatches use **fixed colors that contradict the canvas**: unverified icon = gray hollow circle, machine-confirmed = blue square, human-reviewed = blue circle + gold ring — but on canvas all three are drawn in **type hue** (`typeColor(n.type)`), only the *shape* encodes trust. The legend teaches "blue = machine-confirmed"; the canvas shows an orange square for a machine-confirmed Topic. Users will misread the graph. The detail-panel trust badges repeat the same fixed-blue/gray fiction. | Split the legend into two labeled sections (see Mockup 1): **"Trust · shape"** drawn in neutral graphite (`#8b93a3`) so shape is the only variable, and **"Type · color"** with the real palette dots. Make panel badges match: trust badge = neutral with shape glyph (○/■/◉), type badge = type color. One encoding contract across canvas, legend, and panel. |
| 3 | **High** | Keyboard a11y | The graph is mouse-only. `<canvas>` is not focusable (`tabindex` absent), nodes are unreachable by keyboard, `Esc` does not close the detail panel, no arrow-key pan / `+`/`-` zoom, no visible focus indicator anywhere on the canvas. Only the search box and orphan checkbox are keyboard-operable. | Make canvas focusable (`tabindex="0"`, `role="application"` or `role="img"` with `aria-label` summarizing counts). Implement: `←↑↓→` pan, `+`/`-`/`0` zoom/reset, `Tab`-driven node cycling *or* at minimum `Enter`-in-search already exists — add `Esc` closes panel and returns focus to search. Add `:focus-visible` outline on canvas and panel. |
| 4 | **High** | Text alternative | Screen-reader users get nothing from the graph: canvas has no `role`/`aria-label`, and there is no fallback list of concepts. Legend `<svg>` icons lack `aria-hidden="true"` (decorative, will be announced as images). | `role="img"` + `aria-label="Knowledge graph: 7 concepts, 20 links, 1 dead link. Use search to explore concepts."` on canvas; add `aria-hidden="true"` to legend svgs; append a visually-hidden `<ul>` of concept titles (or an `<details>` "Concept list") as the text alternative. |
| 5 | **Medium** | Discoverability | No neighborhood emphasis: hovering/selecting a node does not highlight its 1-hop neighbors or incident edges (Obsidian and Kumu both do this; it is the primary graph-reading interaction). No depth control. | On hover/select: draw 1-hop neighbors + incident edges at full opacity, dim the rest to 0.15 (reuse the existing `match` dimming path with a `focusId` variable). Add a "depth: 1 / 2 / all" segmented control next to search for local-graph exploration. |
| 6 | **Medium** | Detail panel | Panel shows title/badges/frontmatter/body but **no connections** — no "Links to" / "Linked from" lists, so you cannot traverse the graph from the panel (Kumu's profile panel and Obsidian's backlinks both do this). | Add a "Connections" section (see Mockup 2): two labeled lists of neighbor buttons; clicking one selects + centers that node. Derive from the existing `edges` array — no model change needed. |
| 7 | **Medium** | Detail panel readability | (a) The frontmatter table duplicates keys already displayed above it (`title`, `type`, `description`, `tags`). (b) Body is dumped as **raw markdown** in `<pre>` — users read `#`, `[text](target)`, `---` instead of content. | (a) Exclude `title`, `type`, `description`, `tags` from the table (render tags as chips under badges). (b) Render a minimal markdown subset to HTML: `#`–`###`, `**bold**`, `*italic*`, `` `code` ``, `-` lists, and `[text](target)` → buttons that select the target concept when it resolves, plain text otherwise. Escape HTML first, then apply transforms. |
| 8 | **Medium** | Performance feel | 600 nodes / 1791 edges = **~2.0 s synchronous main-thread freeze** during `layout()` on a fast desktop CPU (measured in Node replicating the exact physics; laptops will be 2–3× slower). No loading indicator — the page appears hung. Complexity is O(n²) per tick with only a distance cutoff, so 2000 nodes extrapolates to tens of seconds. The code comment "500+ nodes stay smooth" is incorrect. The resulting layout also collapses into a dense central hairball (see large screenshot). | Chunk `layout()` into `requestAnimationFrame` slices (e.g. 12 ticks/frame) behind a determinate "Laying out N concepts…" overlay with a progress bar; keep the early-exit cooling check. For >1500 nodes, raise repulsion / REST or switch to a grid-spatial-hash for the repulsion pass. Tune defaults (stronger `K_REP`, weaker `GRAV`) to open up the core. |
| 9 | **Medium** | Color encoding | `typeColor` hashes the type name to an arbitrary hue: collisions are possible (two types, near-identical hues), it is not colorblind-safe, and measured contrast of `hsl(h,62%,52%)` on `#0f1115` drops to **2.40:1 at hue 240° / 3.14:1 at 270°** — below the 3:1 WCAG non-text minimum for the hollow-circle strokes. Some nodes are literally hard to see. | Replace the hash with a curated categorical palette assigned by sorted type name — Okabe–Ito (colorblind-safe) or Tableau 10 — all verified ≥3:1 on `#0f1115`. Keep hues stable across renders by indexing the sorted type list. |
| 10 | **Medium** | Navigation | No way back to the initial view: after panning/zooming into the void there is no reset-view affordance; double-click zoom is unimplemented. | Add a "Reset view" button (⌂ icon) in the header or overlaying top-right of canvas that calls the existing `fitView()` + `draw()`. Add double-click → zoom in one step centered on cursor. |
| 11 | **Medium** | Search feedback | Search dims non-matches (nodes 0.12, edges 0.08) but gives **no match count and no empty-result message** — typing gibberish leaves a near-blank canvas with no explanation. | Show a live result line in/near the search box: `3 of 7 concepts` (update on input), and when zero match show a small toast/overlay "No concepts match 'xyz' — clear the search to restore the graph." Consider `aria-live="polite"` on the count. |
| 12 | **Low** | Hint bar | `#hint` ("drag to move · scroll to zoom · click a node for details") never dismisses, overlaps the canvas permanently, is desktop-worded (no pinch-zoom exists on touch), and measures **3.60:1** (`#6b7280` on `#171a21`) — fails WCAG AA for 11px text. | Auto-fade the hint after the first successful drag or node select (keep a `?` button to recall it). Reword: "drag to pan · scroll or pinch to zoom · click a node". Raise to `#9aa0ae` (6.64:1, passes). |
| 13 | **Low** | Legend completeness | Legend silently truncates types at 12 (no "+N more"), never explains the **node-size ∝ degree** encoding, and omits the red-diamond **ghost node** shape (only the dashed line is shown). | Add "+N more" overflow chip; add a "Size · links" row (three circles S/M/L, "fewer links → more links"); add the diamond swatch next to the dead-link line swatch (see Mockup 1). |
| 14 | **Low** | Touch | Pointer events give basic touch-drag, but pinch-to-zoom is unimplemented — mobile users cannot zoom at all. | Implement two-pointer pinch (track two active pointers, zoom about midpoint) — ~30 lines reusing the wheel-zoom math. |
| 15 | **Low** | Labels | For ≤80 nodes every label draws always, centered, with no truncation or collision handling — long titles ("Structure and Interpretation of Computer Programs") collide in dense areas. | Truncate labels to ~28 chars with ellipsis (full title in `<title>`-equivalent hover state / panel); skip labels whose screen boxes overlap already-drawn ones (cheap greedy declutter). |
| 16 | **Low** | Code hygiene | Search concatenates fields with a literal two-character `\n` (backslash + n): the template's `"\\\\n"` becomes `"\\n"` in JS, not a newline. Harmless today, but it means cross-field queries can never match at boundaries and it signals an untested path. | Use `"\n"` (real newline) or `" "` as the joiner and add a unit test for the search predicate. |
| 17 | **Low** | Small graphs | `fitView` caps scale at 2.5 with +160 world-unit padding, so a 1–2 node bundle renders as tiny glyphs adrift in a large viewport. | When `nodes.length <= 4`, allow scale up to 5 and reduce padding, or center with a minimum on-screen node radius of ~28px. |

**What already works (keep):** offline single-file output; header stats line (`7 concepts · 20 links · 1 dead link`) — excellent first-impression summary; zoom-to-cursor wheel math; click-vs-drag disambiguation (`moved < 5`); degree-scaled nodes; red dashed dead-link edges + ghost diamonds + stats count; orphan toggle preserving the selected node; `Enter`-in-search selects + centers first match; DPR-aware canvas sizing; `prefers` dark-only palette is coherent.

**Best-in-class gap summary:** Obsidian = hover-neighborhood spotlight + backlink panel + search match counts (we have none of the three). Gephi = honest categorical palettes + degree ranking with legend + label declutter (we fake none, document none). Kumu = directional/emphasized connections + profile-panel traversal + reset/focus controls (we have neither). The mockups below close these gaps in the cheapest order.

## 3. Interaction mockups

### Mockup A — Legend v2 (honest two-channel encoding)

A bottom-left card, `max-width: 320px`, with two labeled groups and a collapse toggle:

```
┌ Legend ───────────────────────── [–] ┐
│ TRUST · SHAPE                        │
│  ○  unverified — hollow circle       │
│  ■  machine-confirmed — filled square│
│  ◉  human-reviewed — filled circle   │
│      + amber ring                    │
│  ◇╌  dead link — target not in bundle│
│ TYPE · COLOR                         │
│  ● Course  ● Instructor  ● Resource  │
│  ● Topic  (+1 more)                  │
│ SIZE · LINKS                         │
│  ○  ○  ●   fewer → more links        │
└──────────────────────────────────────┘
```

Spec: trust glyphs drawn in neutral `#8b93a3` (shape is the only variable — matches canvas, since
canvas uses type hue for fills/strokes). Type dots use the curated palette from fix #9, assigned by
sorted type name; overflow beyond 8 shown as a `(+N more)` chip with `title` listing the rest.
Size row: three circles at radii 6 / 10 / 15 px labeled "fewer → more links". Whole card wrapped in
`<details open>`-style collapse so it never permanently occludes the graph on small screens.
`aria-hidden="true"` on all decorative svgs.

### Mockup B — Detail panel v2 (traversable, non-redundant)

```
┌─────────────────────────────────────┐
│ Sorting Algorithms              [×] │  ← h2 + close × (top-right); Esc closes
│ `topics/sorting`                    │  ← id, mono, existing style
│ [● Topic] [◉ human-reviewed]        │  ← type chip (type color) + trust chip
│                                     │     (neutral + shape glyph, fix #2)
│ [core] [algorithms]                 │  ← tags as chips (moved out of table)
│ Divide-and-conquer methods for      │  ← description, existing style
│ ordering data…                      │
│ CONNECTIONS                         │
│  Links to (3)      │ Linked from (2) │
│  [CS 201: Data…]   │ [quicksort]     │  ← buttons; click = select + center
│  [Big-O notation]  │ [mergesort]     │     neighbor (fix #6); ghost targets
│  [◇ nope/missing]  │                 │     get the dead-link chip style
│ METADATA                            │
│  key          │ value                │  ← frontmatter MINUS title/type/
│  …           │ …                    │     description/tags (fix #7a)
│ BODY                                │
│  Rendered markdown: headings, bold, │  ← minimal md renderer (fix #7b);
│  lists; [concept links] are buttons │     internal links become buttons
│  that jump to the concept.          │
└─────────────────────────────────────┘
```

Spec: panel width 360px (keep), `max-height` keep; `×` button 32px hit target; focus moves to `×`
on open and returns to the invoking control on close; neighbor buttons show a small trust-shape
glyph + type-color dot before the label so the encoding stays visible while traversing.

### Mockup C — Empty, loading, and error states (honest states)

* **True empty (0 concepts only — after fix #1):** keep the existing card copy and centered layout
(verified good), but add the bundle name and a concrete next step:
"**cs-curriculum** has no concepts yet. Add `*.md` files with YAML frontmatter to the bundle
directory, then re-render." Secondary button: "How bundles work →" linking to the docs section
(if a docs URL is known; otherwise omit the button rather than inventing one).
* **Loading (new):** because layout blocks, show a determinate overlay on boot for bundles with
>150 concepts: spinner-free progress bar "Laying out 600 concepts… 42%" driven by the chunked
`requestAnimationFrame` layout from fix #8; overlay fades (200ms) when the first frame draws.
* **Error (new):** if `BUNDLE.nodes` fails to parse, render an error card — "Could not read this
bundle: <reason>" — instead of the current silent blank canvas. Never show the empty-state card
for a non-empty bundle (regression test from fix #1 covers this).

## 4. Re-review gate

**UX Panel D supervises every builder iteration of `viz.html`.** Each build addressing this report
must be re-submitted for re-review; Panel D will re-run the render + screenshot + interaction audit
and will return **APPROVED** only when: finding #1 is fixed and regression-tested, findings #2–#4
are resolved, and at least the mockup-A/B/C changes (or equivalently good alternatives) are in
place. Do not consider viz done without a Panel D re-review pass.

---
*Panel D verdict: CHANGES-REQUIRED — 1 critical, 3 high, 7 medium, 6 low (17 findings). Strong
bones; fix the overlay bug, tell the truth in the legend, and let keyboard users in.*
