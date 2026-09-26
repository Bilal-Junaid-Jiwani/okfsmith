# DESIGN_TOKENS.md — okfsmith Docs Site

**Author:** Worker #2 (UX Designer) · 2026-09-26
**Reference visual target:** Claude Code docs (`https://code.claude.com/docs/en/setup`) — dark 3-column docs layout.
**Constraints:** zero external dependencies (no Google Fonts, no CDN CSS/JS). Plain CSS only, all assets local with relative paths. Never commit this spec file itself.

---

## 1. Color Palette (dark theme)

All colors defined once as CSS custom properties in `:root`. Use tokens, never raw hexes in component CSS.

| Token | Hex | Usage |
|---|---|---|
| `--bg` | `#16150F` | Page background (warm near-black) |
| `--bg-2` | `#1C1A15` | Slightly raised page areas (e.g. tab bar strip) |
| `--surface` | `#201E17` | Cards, sidebar panel, TOC panel, search modal |
| `--surface-2` | `#262219` | Hover states, table row hover, code block header |
| `--border` | `#333027` | Default hairline borders |
| `--border-strong` | `#46412F` | Borders on focus/emphasis, table rules |
| `--text` | `#F4F1E8` | Primary text (warm off-white) |
| `--text-2` | `#C9C3B2` | Secondary text (body of muted regions, meta) |
| `--text-3` | `#8E8773` | Tertiary/muted text (timestamps, captions, footer) |
| `--accent` | `#D97757` | Terracotta primary accent — active tab underline, active sidebar item, primary links, CTA hover, key highlights |
| `--accent-strong` | `#E8896B` | Accent on hover / text on dark |
| `--accent-dim` | `#3A2620` | Accent wash backgrounds (active sidebar pill, admonition tint) |
| `--accent-text` | `#F0A37E` | Accent-colored body text where `#D97757` fails contrast |
| `--code-bg` | `#0E0D0B` | Code block body background |
| `--code-header-bg` | `#181611` | Code block header strip |
| `--inline-code-bg` | `#2A2519` | Inline `<code>` background |
| `--inline-code-fg` | `#EFCFA4` | Inline `<code>` text |
| `--link` | `#E9B48C` | Body link color |
| `--link-hover` | `#F5CDA6` | Body link hover (plus underline) |
| `--success` | `#7FB069` | Tip/success admonition accent |
| `--success-bg` | `#1E2B1C` | Tip/success admonition wash |
| `--warning` | `#E0A458` | Warning admonition accent |
| `--warning-bg` | `#2E2415` | Warning admonition wash |
| `--danger` | `#DE6B5A` | Danger admonition accent |
| `--danger-bg` | `#2E1B17` | Danger admonition wash |
| `--note` | `#D97757` | Note admonition accent (same terracotta family) |
| `--note-bg` | `#2E2019` | Note admonition wash |
| `--focus-ring` | `#D9775780` | Keyboard focus outline (8-digit hex = 50% alpha) |
| `--overlay` | `#0B0A08CC` | Drawer/modal scrim (8-digit hex = 80% alpha) |

**Selection:** `background: #D97757; color: #16150F;`

---

## 2. Typography

No webfonts. Serif display stack must look good from system fonts alone.

### Stacks
```css
--font-serif: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia,
              "Charter", "Bitstream Charter", "Sitka Text", "Noto Serif", serif;
--font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "Inter", Roboto,
             "Helvetica Neue", Arial, "Noto Sans", sans-serif;
--font-mono: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas,
             "Liberation Mono", "DejaVu Sans Mono", monospace;
```

### Scale

| Element | Font | Size | Line-height | Weight | Notes |
|---|---|---|---|---|---|
| `h1` (page title) | serif | `2.75rem` (44px) | `1.15` | 600 | Letter-spacing `-0.01em`; the "BIG serif title" |
| `h2` | sans | `1.5rem` (24px) | `1.3` | 650 | `margin-top: 2.5rem` |
| `h3` | sans | `1.25rem` (20px) | `1.35` | 650 | `margin-top: 2rem` |
| `h4` | sans | `1.0625rem` (17px) | `1.4` | 650 | `margin-top: 1.5rem` |
| Body | sans | `1rem` (16px) | `1.7` | 400 | Color `--text`; max measure 68ch |
| Small (captions, meta) | sans | `0.8125rem` (13px) | `1.5` | 400 | Color `--text-3` |
| Code block | mono | `0.875rem` (14px) | `1.65` | 400 | |
| Inline code | mono | `0.875em` | `1` | 400 | Relative to parent |
| Eyebrow | sans | `0.75rem` (12px) | `1.4` | 700 | Small caps (see §4) |
| Sidebar nav | sans | `0.875rem` (14px) | `1.4` | 500 / 600 active | |
| TOC | sans | `0.8125rem` (13px) | `1.5` | 400 / 600 active | |

**Fluid h1:** `clamp(2rem, 1.4rem + 3vw, 2.75rem)` so mobile keeps the serif punch without overflow.

---

## 3. Layout

### Grid
```css
.docs-shell {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr) 230px;
  gap: 3rem;                       /* 48px gutters */
  max-width: 1440px;
  margin-inline: auto;
  padding-inline: 2rem;
}
```
- **Main column:** content inner max-width `46rem` (≈736px) — keeps prose measure readable inside the wide column.
- **Left sidebar:** 260px, `position: sticky; top: calc(64px + 49px + 1.5rem)` (below top bar + tab bar), `max-height: calc(100vh - that)`, `overflow-y: auto`.
- **Right TOC:** 230px, same sticky treatment, shows on `min-width: 1100px` only.

### Chrome heights
- **Top bar:** 64px fixed (`position: sticky; top: 0; z-index: 50`). Background `var(--bg)` with `border-bottom: 1px solid var(--border)` and `backdrop-filter: blur(8px)` over a 90% opaque bg (`#16150FE6`).
- **Tab bar:** 48px, sticky directly under the top bar (`top: 64px; z-index: 40`), same border treatment. Horizontally scrollable on narrow screens (no wrap, `overflow-x: auto`, hidden scrollbar).

### Breakpoints
| Breakpoint | Behavior |
|---|---|
| `≥ 1100px` | Full 3 columns (260 / 1fr / 230). |
| `800–1099px` | Right TOC hidden (`display: none`); grid becomes `260px minmax(0, 1fr)`. |
| `< 800px` | Left sidebar hidden from grid; becomes off-canvas drawer (see §4). Grid becomes single column; top bar gains hamburger button; TOC collapses into a `<details>` block at the top of main ("On this page"). |
| `< 520px` | Reduce paddings (`1rem`), h1 fluid clamp takes over, tables get horizontal scroll wrappers, search box in top bar shrinks to icon-only button opening the modal. |

---

## 4. Components

### 4.1 Top bar
- **Left:** logo mark (local SVG, 28×28) + wordmark "okfsmith" (sans, 600, 1rem) + divider + "Docs" label (sans, 500, 0.875rem, `--text-2`) + language chip ("EN", 0.75rem, bordered pill, `--text-3`).
- **Center/right:** search trigger — a real `<button>` styled as an input: `min-width: 220px`, `background: var(--surface)`, `border: 1px solid var(--border)`, `border-radius: 8px`, `color: var(--text-3)`, with trailing kbd hint `<kbd>Ctrl</kbd><kbd>K</kbd>`. Opens the search modal.
- **Right:** CTA button ("Get started" / `pip install okfsmith` deep link): `background: var(--accent); color: #16150F; font-weight: 600; border-radius: 8px; padding: 0.5rem 1rem`. Hover: `background: var(--accent-strong)`.

### 4.2 Tabs
- Tab list under the top bar: e.g. **Docs** (active), **API reference**, **Changelog**, **Community**.
- Tab link: `padding: 0.75rem 1rem; color: var(--text-2); font-size: 0.875rem; font-weight: 500; border-bottom: 2px solid transparent;`
- **Active tab:** `color: var(--text); border-bottom-color: var(--accent); font-weight: 600;`
- Hover (inactive): `color: var(--text); border-bottom-color: var(--border-strong);`

### 4.3 Sidebar nav
- Groups: `<div class="nav-group">` with group label (`0.75rem`, 700, uppercase, `letter-spacing: 0.06em`, `--text-3`, `margin: 1.5rem 0 0.5rem`).
- Nav item (anchor): `display: block; padding: 0.375rem 0.75rem; border-radius: 6px; color: var(--text-2); font-size: 0.875rem; font-weight: 500; border-left: 2px solid transparent;`
  - **Hover:** `background: var(--surface-2); color: var(--text);`
  - **Active:** `background: var(--accent-dim); color: var(--accent-text); font-weight: 600; border-left-color: var(--accent);` — highlighted in the terracotta family, never plain white-on-dark.
- Nested children indent `1rem` with a subtle `border-left: 1px solid var(--border)` guide.

### 4.4 Eyebrow + h1 + Copy-page row
- Page header layout: flex row, title block left, "Copy page" button right, aligned to h1 baseline.
- **Eyebrow:** `font: 700 0.75rem var(--font-sans); text-transform: uppercase; letter-spacing: 0.08em; color: var(--accent-text); margin-bottom: 0.75rem;` (e.g. "GETTING STARTED", "REFERENCE").
- **h1:** serif per §2, `margin: 0 0 1.5rem; color: var(--text);`
- **Copy page button:** ghost style — `border: 1px solid var(--border); background: transparent; color: var(--text-2); border-radius: 8px; padding: 0.375rem 0.75rem; font-size: 0.8125rem;` with a copy SVG icon. Hover: `border-color: var(--border-strong); color: var(--text); background: var(--surface-2);`. On click → "Copied" state for 2s (accent check icon).

### 4.5 Code blocks
- Structure: `<figure class="codeblock">` → header strip (`--code-header-bg`) + `<pre>` body (`--code-bg`).
- Header (optional but recommended): left = language label or filename (`0.75rem mono, --text-3`), right = copy button (icon-only, 28×28, same ghost style; on click shows "Copied" tooltip).
- If no header, the copy button floats top-right inside the `<pre>` (absolute, `opacity: 0` until `:hover`/`:focus-within`).
- Block: `border: 1px solid var(--border); border-radius: 12px; overflow: hidden; margin: 1.5rem 0;`
- `<pre>`: `padding: 1rem 1.25rem; overflow-x: auto; font: 0.875rem/1.65 var(--font-mono); color: var(--text); tab-size: 2;`
- No external highlighter: hand-rolled token colors (span classes): keyword `#E8896B`, string `#A8C686`, comment `#6E6858` (italic), number `#E0A458`, function `#EFCFA4`, operator/punct `--text-2`.

### 4.6 Inline code
`font: 0.875em var(--font-mono); background: var(--inline-code-bg); color: var(--inline-code-fg); padding: 0.15em 0.375em; border-radius: 5px; border: 1px solid #3a3222; white-space: nowrap;`

### 4.7 Tables
- Wrapper: `overflow-x: auto; border: 1px solid var(--border); border-radius: 12px; margin: 1.5rem 0;`
- `th`: `0.75rem sans, 700, uppercase, letter-spacing: 0.05em, --text-3; text-align: left; padding: 0.75rem 1rem; background: var(--surface); border-bottom: 1px solid var(--border-strong);`
- `td`: `padding: 0.75rem 1rem; border-bottom: 1px solid var(--border); font-size: 0.9375rem; vertical-align: top;`
- `tbody tr:hover td { background: var(--surface-2); }` · last row has no bottom border.

### 4.8 Admonition boxes
Structure: `<aside class="admonition note|tip|warning|danger">` with an inline SVG icon + bold title + body.

```css
.admonition {
  display: grid; grid-template-columns: 20px 1fr; gap: 0.75rem;
  border-radius: 12px; padding: 1rem 1.25rem; margin: 1.5rem 0;
  border: 1px solid; font-size: 0.9375rem; line-height: 1.65;
}
.admonition.note    { border-color: #D9775766; background: var(--note-bg); }
.admonition.note    .admon-title { color: var(--accent-text); }
.admonition.tip     { border-color: #7FB06966; background: var(--success-bg); }
.admonition.tip     .admon-title { color: var(--success); }
.admonition.warning { border-color: #E0A45866; background: var(--warning-bg); }
.admonition.warning .admon-title { color: var(--warning); }
.admonition.danger  { border-color: #DE6B5A66; background: var(--danger-bg); }
.admonition.danger  .admon-title { color: var(--danger); }
```
`.admon-title` = sans 700 0.875rem uppercase-ish ("Note", "Tip", "Warning", "Danger") with the icon inheriting its color via `currentColor`.

### 4.9 Search modal (Ctrl+K)
- Trigger: top-bar button (≥520px) or icon-only button (<520px); keyboard: `Ctrl+K` / `⌘+K` toggles.
- Modal: centered, `max-width: 640px`, `top: 15vh`, `background: var(--surface); border: 1px solid var(--border-strong); border-radius: 16px; box-shadow: 0 24px 64px #000000A6;`
- Input row: large input (`1rem`, no border, `background: transparent`) with search icon; `border-bottom: 1px solid var(--border)` separating the results list.
- Results: buttons/rows `padding: 0.75rem 1rem`, hover/active: `background: var(--surface-2)`; result title 0.875rem 600 `--text`, snippet 0.8125rem `--text-3`; keyboard ↑/↓ + Enter navigation, Esc closes.
- Scrim: full-viewport `--overlay`; close on scrim click. Pure vanilla JS (<100 lines), no library. Search index: a local generated `search-index.json` (built at build time, relative path `../search-index.json`).

### 4.10 Mobile drawer (<800px)
- Hamburger button appears in top bar (left of logo). Clicking opens the left nav as an off-canvas drawer: `position: fixed; inset: 0 auto 0 0; width: min(320px, 85vw); background: var(--surface); z-index: 60; transform: translateX(-100%); transition: transform 220ms;` — open state `translateX(0)`, plus `--overlay` scrim behind it.
- Drawer closes on: scrim click, Esc, or nav link click. Focus trapped while open; return focus to hamburger on close.
- Right TOC becomes `<details class="toc-mobile"><summary>On this page</summary>…</details>` at the top of `<main>`: bordered, `border-radius: 12px`, `background: var(--surface)`, collapsed by default.

---

## 5. Motion

**Principle: subtle, functional, never decorative-heavy.** No entrance animations on scroll, no parallax, no animated gradients.

| Property | Value |
|---|---|
| Base transition | `transition: background-color 120ms ease, color 120ms ease, border-color 120ms ease;` on interactive elements (nav items, buttons, tabs, table rows, code copy) |
| Drawer/modal | `220ms cubic-bezier(0.32, 0.72, 0, 1)` for transform/opacity only |
| Focus rings | Instant (no transition); `:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }` |
| Code copy feedback | Opacity fade 150ms |
| Scroll behavior | `scroll-behavior: smooth` for TOC anchor jumps only, wrapped in `@media (prefers-reduced-motion: no-preference)` |
| Reduced motion | `@media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; scroll-behavior: auto !important; } }` |

---

## 6. CSS Custom Property Cheat-Sheet (copy into `styles.css`)

```css
:root {
  --bg: #16150F;
  --bg-2: #1C1A15;
  --surface: #201E17;
  --surface-2: #262219;
  --border: #333027;
  --border-strong: #46412F;
  --text: #F4F1E8;
  --text-2: #C9C3B2;
  --text-3: #8E8773;
  --accent: #D97757;
  --accent-strong: #E8896B;
  --accent-dim: #3A2620;
  --accent-text: #F0A37E;
  --code-bg: #0E0D0B;
  --code-header-bg: #181611;
  --inline-code-bg: #2A2519;
  --inline-code-fg: #EFCFA4;
  --link: #E9B48C;
  --link-hover: #F5CDA6;
  --success: #7FB069;  --success-bg: #1E2B1C;
  --warning: #E0A458;  --warning-bg: #2E2415;
  --danger: #DE6B5A;   --danger-bg: #2E1B17;
  --note: #D97757;     --note-bg: #2E2019;
  --focus-ring: #D9775780;
  --overlay: #0B0A08CC;
  --font-serif: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia,
                "Charter", "Bitstream Charter", "Sitka Text", "Noto Serif", serif;
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "Inter", Roboto,
               "Helvetica Neue", Arial, "Noto Sans", sans-serif;
  --font-mono: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas,
               "Liberation Mono", "DejaVu Sans Mono", monospace;
}
::selection { background: #D97757; color: #16150F; }
```

## 7. Handoff notes for the implementer

1. All paths relative: `styles.css`, `search.js`, `search-index.json`, `logo.svg` live next to or under the docs root — no leading `/`, no CDN.
2. Contrast spot-checks: `--text` on `--bg` ≈ 15.4:1; `--text-3` on `--bg` ≈ 4.6:1 (fine for non-body meta); `--accent-text #F0A37E` on `--note-bg` ≥ 4.5:1 for admonition titles; `--accent #D97757` used only for large/bold UI accents (tab underline, active pill border), never for small body text.
3. Anchor scroll offset: `scroll-margin-top: calc(64px + 48px + 1rem)` on all `h2/h3/h4[id]` so sticky bars never cover headings.
4. Sidebar/TOC active-section highlighting on scroll: optional enhancement via `IntersectionObserver` (vanilla JS, ~20 lines); acceptable to ship static `aria-current="page"` first.
5. File written on branch `feature/docs-site`; **not committed**, per task constraints.
