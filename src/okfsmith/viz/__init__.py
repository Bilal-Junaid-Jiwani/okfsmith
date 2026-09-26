"""Interactive graph visualization of an OKF knowledge bundle.

:func:`render_html` reads a bundle directory and writes a single
self-contained ``viz.html`` file: a force-directed concept graph drawn on a
``<canvas>`` with vanilla JavaScript (no CDN, no external libraries — the
file works fully offline).

Features:

- nodes colored by concept ``type``; shape/badge by trust tier
  (``unverified`` / ``machine-confirmed`` / ``human-reviewed``, per
  :func:`okfsmith.core.spec.trust_tier`)
- edges extracted from markdown links in concept bodies; links whose target
  is not a concept in the bundle are drawn as red dashed dead-link edges
  leading to a ghost node
- click a node for a detail panel (frontmatter table + body as text)
- search box matching id / title / tags
- "show orphans" toggle hides concepts with no links

Python side is stdlib-only; the embedded JavaScript is dependency-free.
"""

from __future__ import annotations

import html
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from okfsmith.core import spec
from okfsmith.core.bundle import Bundle, Concept

__all__ = ["render_html"]


# ---------------------------------------------------------------------------
# Link extraction
# ---------------------------------------------------------------------------

# Inline markdown link: [text](target) — the (?<!\!) skips image links.
_INLINE_LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(\s*<?([^)\s>]+)>?[^)]*\)")
# Reference-style definition: [label]: target  ("optional title")
# Footnote definitions ([^...]: ...) are NOT links and are excluded.
_REFDEF_RE = re.compile(
    r"^[ \t]{0,3}\[(?!\^)[^\]]+\]:"  # [label]: — never a [^footnote]:
    r"[ \t]*<?([^\s>]+)>?"  # the target (no spaces, per CommonMark)
    r"(?:[ \t]+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?"  # optional "title"
    r"[ \t]*$",
    re.MULTILINE,
)
# URI scheme, e.g. https:, mailto:, ftp: — external resources, not concepts.
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def _link_targets(body: str) -> list[str]:
    """Return raw link targets from inline links and reference definitions."""
    targets = [m.group(1) for m in _INLINE_LINK_RE.finditer(body or "")]
    targets += [m.group(1) for m in _REFDEF_RE.finditer(body or "")]
    return targets


def _resolve_target(concept_id: str, raw: str) -> str | None:
    """Resolve a raw markdown link target to a concept id, or ``None``.

    Rules: external URIs (any scheme) and pure ``#fragment`` links are not
    concept links; ``/a/b`` is bundle-absolute; anything else resolves
    relative to the linking concept's directory; a trailing ``.md`` suffix,
    query strings and fragments are stripped; ``.``/``..`` segments collapse.
    """
    raw = (raw or "").strip().strip("<>")
    if not raw or raw.startswith("#"):
        return None
    if _SCHEME_RE.match(raw):
        return None  # external resource — not a concept link
    target = re.split(r"[#?]", raw, maxsplit=1)[0].strip()
    if not target:
        return None
    if target.startswith("/"):
        target = target[1:]
    else:
        base = concept_id.rpartition("/")[0]
        target = f"{base}/{target}" if base else target
    parts: list[str] = []
    for part in target.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    target = "/".join(parts)
    if target.lower().endswith(".md"):
        target = target[: -len(".md")]
    return target or None


# ---------------------------------------------------------------------------
# Node / edge model
# ---------------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    """Convert frontmatter values to JSON-serializable primitives."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _tags_of(frontmatter: dict) -> list[str]:
    tags = frontmatter.get("tags")
    if tags is None:
        return []
    if isinstance(tags, str):
        return [tags]
    try:
        return [str(t) for t in tags]
    except TypeError:
        return [str(tags)]


def _node_for(concept: Concept) -> dict[str, Any]:
    fm = concept.frontmatter or {}
    return {
        "id": concept.id,
        "type": str(fm.get("type") or "unknown"),
        "title": str(fm.get("title") or concept.id),
        "trust": spec.trust_tier(fm),
        "description": str(fm.get("description") or ""),
        "tags": _tags_of(fm),
        "frontmatter": _jsonable(dict(fm)),
        "body": concept.body or "",
    }


def _build_model(bundle: Bundle) -> dict[str, Any]:
    """Build the ``{"nodes": [...], "edges": [...]}`` model for the template."""
    concepts = list(bundle.iter_concepts())
    nodes = [_node_for(c) for c in concepts]
    ids = {n["id"] for n in nodes}
    edges: list[dict[str, Any]] = []
    for concept in concepts:
        seen: set[str] = set()
        for raw in _link_targets(concept.body):
            target = _resolve_target(concept.id, raw)
            if not target or target == concept.id or target in seen:
                continue
            seen.add(target)
            edges.append(
                {"from": concept.id, "to": target, "dead": target not in ids}
            )
    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# HTML template (single file, no external resources)
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ &mdash; OKF bundle graph</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
         background: #0f1115; color: #e6e8ec; display: flex; flex-direction: column;
         height: 100vh; overflow: hidden; }
  header { display: flex; align-items: center; gap: 12px; padding: 10px 14px;
           background: #171a21; border-bottom: 1px solid #2a2e38; flex-wrap: wrap; }
  header h1 { font-size: 15px; margin: 0; font-weight: 600; white-space: nowrap; }
  header .stats { font-size: 12px; color: #9aa0ae; white-space: nowrap; }
  #search { margin-left: auto; background: #0f1115; border: 1px solid #2a2e38;
            color: #e6e8ec; border-radius: 6px; padding: 6px 10px; width: 220px; }
  .toggle { font-size: 12px; color: #9aa0ae; display: flex; align-items: center; gap: 6px;
            white-space: nowrap; cursor: pointer; }
  main { position: relative; flex: 1; min-height: 0; }
  #graph { position: absolute; inset: 0; width: 100%; height: 100%; display: block;
           cursor: grab; }
  #detail { position: absolute; top: 12px; right: 12px; width: 360px; max-width: 90vw;
            max-height: calc(100% - 24px); overflow: auto; background: #171a21f2;
            border: 1px solid #2a2e38; border-radius: 10px; padding: 14px 16px;
            display: none; }
  #detail.open { display: block; }
  #detail h2 { margin: 0 0 4px; font-size: 16px; overflow-wrap: anywhere; }
  #detail .meta { font-size: 12px; color: #9aa0ae; margin-bottom: 8px; }
  #detail .meta code { background: #0f1115; padding: 1px 6px; border-radius: 4px; }
  .badges { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
  .badge { font-size: 11px; padding: 2px 8px; border-radius: 999px; color: #0f1115;
           font-weight: 600; }
  .badge.trust-unverified { background: #8b93a3; color: #0f1115; }
  .badge.trust-machine-confirmed { background: #58a6ff; color: #0f1115; }
  .badge.trust-human-reviewed { background: #d4a017; color: #0f1115; }
  .badge.dead { background: transparent; color: #ff7b72; border: 1px dashed #ff7b72; }
  #detail .desc { font-size: 13px; color: #c6cbd4; }
  #detail table { width: 100%; border-collapse: collapse; font-size: 12px; margin: 8px 0; }
  #detail th, #detail td { text-align: left; padding: 4px 6px; border-bottom: 1px solid #2a2e38;
                           vertical-align: top; overflow-wrap: anywhere; }
  #detail th { color: #9aa0ae; font-weight: 600; width: 34%; }
  #detail h3 { font-size: 12px; text-transform: uppercase; letter-spacing: .06em;
               color: #9aa0ae; margin: 12px 0 4px; }
  #detail pre { font-size: 12px; background: #0f1115; border: 1px solid #2a2e38;
                border-radius: 6px; padding: 8px; white-space: pre-wrap;
                overflow-wrap: anywhere; max-height: 320px; overflow: auto; }
  #detail button { margin-top: 10px; background: #2a2e38; color: #e6e8ec; border: 0;
                   border-radius: 6px; padding: 6px 12px; cursor: pointer; }
  #legend { position: absolute; left: 12px; bottom: 12px; background: #171a21ee;
            border: 1px solid #2a2e38; border-radius: 8px; padding: 8px 12px;
            font-size: 11px; color: #9aa0ae; max-width: 300px; }
  #legend .row { display: flex; align-items: center; gap: 8px; margin: 3px 0; }
  #legend svg { flex: none; }
  #legend .types { display: flex; flex-wrap: wrap; gap: 4px 8px; margin-top: 4px; }
  #legend .chip { display: inline-flex; align-items: center; gap: 4px; }
  #legend .dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
  #empty { position: absolute; inset: 0; display: flex; align-items: center;
           justify-content: center; text-align: center; padding: 24px; }
  #empty .card { max-width: 420px; background: #171a21; border: 1px solid #2a2e38;
                 border-radius: 12px; padding: 28px; }
  #empty h2 { margin-top: 0; }
  #empty p { color: #9aa0ae; font-size: 14px; }
  #hint { position: absolute; left: 12px; top: 12px; font-size: 11px; color: #6b7280;
          background: #171a21cc; padding: 4px 10px; border-radius: 6px;
          border: 1px solid #2a2e38; }
</style>
</head>
<body>
<header>
  <h1>__TITLE__</h1>
  <span class="stats">__STATS__</span>
  <input id="search" type="search" placeholder="Search id, title, tags&hellip;" aria-label="Search concepts">
  <label class="toggle"><input id="orphans" type="checkbox" checked> show orphans</label>
</header>
<main>
  <canvas id="graph"></canvas>
  <div id="hint">drag to move &middot; scroll to zoom &middot; click a node for details</div>
  <aside id="detail" aria-label="Concept details"></aside>
  <div id="legend" aria-label="Legend"></div>
  <div id="empty" hidden>
    <div class="card">
      <h2>Nothing to visualize yet</h2>
      <p>This bundle has no concepts. Add some <code>*.md</code> concept files
      (with YAML frontmatter) to the bundle directory and re-render.</p>
    </div>
  </div>
</main>
<script>
"use strict";
/* Self-contained force-directed knowledge-graph viewer.
   Vanilla JS + canvas 2d. No libraries, no network. */
const BUNDLE = __BUNDLE_JSON__;

const canvas = document.getElementById("graph");
const ctx = canvas.getContext("2d");
const panel = document.getElementById("detail");
const searchBox = document.getElementById("search");
const orphanBox = document.getElementById("orphans");
const legend = document.getElementById("legend");

/* ---------------- data ---------------- */
const nodes = BUNDLE.nodes.map((n, i) => Object.assign(
  { i, x: 0, y: 0, vx: 0, vy: 0, deg: 0, ghost: false, match: true }, n));
const byId = new Map(nodes.map(n => [n.id, n]));
const edges = [];
for (const e of BUNDLE.edges) {
  const a = byId.get(e.from);
  if (!a) continue;
  let b = byId.get(e.to);
  if (!b && e.dead) {                       // ghost node marks a dead link
    b = { id: e.to, type: "missing", title: e.to, trust: "unverified",
          description: "Link target is not present in this bundle.",
          tags: [], frontmatter: {}, body: "", ghost: true,
          i: nodes.length, x: 0, y: 0, vx: 0, vy: 0, deg: 0, match: true };
    nodes.push(b);
    byId.set(b.id, b);
  }
  if (!b || a === b) continue;
  edges.push({ a, b, dead: !!e.dead });
  a.deg++;
  b.deg++;
}
const orphanIds = new Set(nodes.filter(n => !n.ghost && n.deg === 0).map(n => n.id));

if (nodes.length === 0) {
  document.getElementById("empty").hidden = false;
  canvas.style.display = "none";
}

/* ---------------- helpers ---------------- */
function esc(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function fmtVal(v) {
  return (v !== null && typeof v === "object") ? JSON.stringify(v) : String(v);
}
function hueFor(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h % 360;
}
function typeColor(t) { return "hsl(" + hueFor(String(t)) + ", 62%, 52%)"; }
function nodeRadius(n) { return 6 + Math.min(9, n.deg); }   // degree-scaled

/* ---------------- camera ---------------- */
const view = { cx: 0, cy: 0, scale: 1 };
function resize() {
  const dpr = window.devicePixelRatio || 1;
  const r = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.round(r.width * dpr));
  canvas.height = Math.max(1, Math.round(r.height * dpr));
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
function w2s(x, y) {
  const r = canvas.getBoundingClientRect();
  return { x: (x - view.cx) * view.scale + r.width / 2,
           y: (y - view.cy) * view.scale + r.height / 2 };
}
function s2w(px, py) {
  const r = canvas.getBoundingClientRect();
  return { x: (px - r.width / 2) / view.scale + view.cx,
           y: (py - r.height / 2) / view.scale + view.cy };
}
function fitView() {
  if (!nodes.length) return;
  let x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9;
  for (const n of nodes) {
    x0 = Math.min(x0, n.x); x1 = Math.max(x1, n.x);
    y0 = Math.min(y0, n.y); y1 = Math.max(y1, n.y);
  }
  const r = canvas.getBoundingClientRect();
  view.cx = (x0 + x1) / 2; view.cy = (y0 + y1) / 2;
  view.scale = Math.min(r.width / Math.max(1, x1 - x0 + 160),
                        r.height / Math.max(1, y1 - y0 + 160), 2.5);
}

/* ---------------- physics (simple force-directed) ---------------- */
function tick() {
  const n = nodes.length;
  const K_REP = 2600, K_SPR = 0.02, REST = 90, GRAV = 0.02, CUTOFF2 = 90000;
  for (let i = 0; i < n; i++) {                     // pairwise repulsion
    const a = nodes[i];
    for (let j = i + 1; j < n; j++) {
      const b = nodes[j];
      let dx = a.x - b.x, dy = a.y - b.y;
      let d2 = dx * dx + dy * dy;
      if (d2 > CUTOFF2) continue;                   // ignore far pairs: O(n^2) stays fast
      if (d2 < 1) { dx = Math.random() - .5; dy = Math.random() - .5; d2 = 1; }
      const d = Math.sqrt(d2), f = K_REP / d2;
      const fx = f * dx / d, fy = f * dy / d;
      a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
    }
  }
  for (const e of edges) {                          // springs along edges
    const dx = e.b.x - e.a.x, dy = e.b.y - e.a.y;
    const d = Math.hypot(dx, dy) || 1;
    const f = K_SPR * (d - REST);
    const fx = f * dx / d, fy = f * dy / d;
    e.a.vx += fx; e.a.vy += fy; e.b.vx -= fx; e.b.vy -= fy;
  }
  let maxV = 0;
  for (const nd of nodes) {                         // gravity + damping + integrate
    nd.vx += -nd.x * GRAV; nd.vy += -nd.y * GRAV;
    nd.vx *= 0.86; nd.vy *= 0.86;
    nd.x += nd.vx; nd.y += nd.vy;
    maxV = Math.max(maxV, Math.abs(nd.vx), Math.abs(nd.vy));
  }
  return maxV;
}
function layout() {
  nodes.forEach((nd, i) => {                        // spiral start, no overlap clump
    const r = 26 * Math.sqrt(i), a = i * 2.39996;   // golden angle
    nd.x = r * Math.cos(a); nd.y = r * Math.sin(a);
  });
  const maxTicks = nodes.length > 400 ? 150 : 400;  // bounded: 500+ nodes stay smooth
  for (let t = 0; t < maxTicks; t++) {
    if (tick() < 0.05) break;                       // cooled: stop early
  }
}

/* ---------------- drawing ---------------- */
let hovered = null, selected = null, dragged = null;
function nodeVisible(n) {
  return orphanBox.checked || !orphanIds.has(n.id) || n === selected;
}
function drawNode(n) {
  const p = w2s(n.x, n.y), r = nodeRadius(n);
  ctx.save();
  if (!n.match) ctx.globalAlpha = 0.12;             // search dimming
  if (n.ghost) {                                    // dead-link target: red diamond
    ctx.strokeStyle = "#ff7b72"; ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(p.x, p.y - r); ctx.lineTo(p.x + r, p.y);
    ctx.lineTo(p.x, p.y + r); ctx.lineTo(p.x - r, p.y);
    ctx.closePath(); ctx.stroke();
  } else if (n.trust === "unverified") {            // hollow circle
    ctx.strokeStyle = typeColor(n.type); ctx.lineWidth = 2.5;
    ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, 7); ctx.stroke();
  } else if (n.trust === "machine-confirmed") {     // filled square
    ctx.fillStyle = typeColor(n.type);
    const s = r * 1.7;
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(p.x - s / 2, p.y - s / 2, s, s, 3);
    else ctx.rect(p.x - s / 2, p.y - s / 2, s, s);
    ctx.fill();
  } else {                                          // human-reviewed: filled circle + gold ring
    ctx.fillStyle = typeColor(n.type);
    ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, 7); ctx.fill();
    ctx.strokeStyle = "#d4a017"; ctx.lineWidth = 3;
    ctx.beginPath(); ctx.arc(p.x, p.y, r + 3, 0, 7); ctx.stroke();
  }
  if (n === selected || n === hovered) {            // selection halo
    ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.arc(p.x, p.y, r + 7, 0, 7); ctx.stroke();
  }
  ctx.restore();
}
function drawLabel(n) {
  const p = w2s(n.x, n.y);
  ctx.save();
  if (!n.match) ctx.globalAlpha = 0.25;
  ctx.font = "11px system-ui, sans-serif";
  ctx.fillStyle = "#dfe3ea";
  ctx.strokeStyle = "#0f1115"; ctx.lineWidth = 3;
  const y = p.y + nodeRadius(n) + 13;
  ctx.strokeText(n.title, p.x, y); ctx.fillText(n.title, p.x, y);
  ctx.restore();
}
function draw() {
  const r = canvas.getBoundingClientRect();
  ctx.clearRect(0, 0, r.width, r.height);
  ctx.textAlign = "center";
  for (const e of edges) {                          // edges under nodes
    if (!nodeVisible(e.a) || !nodeVisible(e.b)) continue;
    const a = w2s(e.a.x, e.a.y), b = w2s(e.b.x, e.b.y);
    ctx.save();
    if (!e.a.match || !e.b.match) ctx.globalAlpha = 0.08;
    if (e.dead) {                                   // dead links: red dashed
      ctx.strokeStyle = "#ff7b72"; ctx.lineWidth = 1.5;
      ctx.setLineDash([6, 4]);
    } else {
      ctx.strokeStyle = "#4b5263"; ctx.lineWidth = 1.2;
      ctx.setLineDash([]);
    }
    ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    ctx.restore();
  }
  for (const n of nodes) if (nodeVisible(n)) drawNode(n);
  const showAll = nodes.length <= 80;               // labels get noisy on big graphs
  for (const n of nodes) {
    if (!nodeVisible(n)) continue;
    if (showAll || n === selected || n === hovered) drawLabel(n);
  }
}

/* ---------------- legend ---------------- */
(function buildLegend() {
  const trustRows = [
    ["unverified", "hollow circle"],
    ["machine-confirmed", "filled square"],
    ["human-reviewed", "filled circle + gold ring"],
  ];
  let h = "";
  for (const [tier, shape] of trustRows) {
    h += '<div class="row"><svg width="16" height="16">'
      + (tier === "unverified"
          ? '<circle cx="8" cy="8" r="5" fill="none" stroke="#8b93a3" stroke-width="2"/>'
          : tier === "machine-confirmed"
          ? '<rect x="3" y="3" width="10" height="10" rx="2" fill="#58a6ff"/>'
          : '<circle cx="8" cy="8" r="5" fill="#58a6ff"/>'
            + '<circle cx="8" cy="8" r="7" fill="none" stroke="#d4a017" stroke-width="2"/>')
      + "</svg><span><b>" + tier + "</b> &mdash; " + shape + "</span></div>";
  }
  h += '<div class="row"><svg width="16" height="16">'
    + '<line x1="1" y1="8" x2="15" y2="8" stroke="#ff7b72" stroke-width="2"'
    + ' stroke-dasharray="4 3"/></svg><span><b>dead link</b> &mdash; target not in bundle</span></div>';
  const types = [...new Set(nodes.filter(n => !n.ghost).map(n => n.type))].sort().slice(0, 12);
  if (types.length) {
    h += '<div class="types">' + types.map(t =>
      '<span class="chip"><span class="dot" style="background:' + typeColor(t) + '"></span>'
      + esc(t) + "</span>").join("") + "</div>";
  }
  legend.innerHTML = h;
})();

/* ---------------- detail panel ---------------- */
function select(n, center) {
  selected = n;
  if (center) { view.cx = n.x; view.cy = n.y; }
  const fm = n.frontmatter || {};
  const rows = Object.keys(fm).map(k =>
    "<tr><th>" + esc(k) + "</th><td>" + esc(fmtVal(fm[k])) + "</td></tr>").join("");
  panel.innerHTML =
    "<h2>" + esc(n.title) + "</h2>"
    + '<div class="meta"><code>' + esc(n.id) + "</code></div>"
    + '<div class="badges">'
    + '<span class="badge" style="background:' + typeColor(n.type) + '">' + esc(n.type) + "</span>"
    + '<span class="badge trust-' + esc(n.trust) + '">' + esc(n.trust) + "</span>"
    + (n.ghost ? '<span class="badge dead">dead-link target</span>' : "")
    + "</div>"
    + (n.description ? '<p class="desc">' + esc(n.description) + "</p>" : "")
    + (rows ? "<table>" + rows + "</table>" : "")
    + (n.body ? "<h3>body</h3><pre>" + esc(n.body) + "</pre>" : "")
    + '<button id="close-panel" type="button">close</button>';
  panel.classList.add("open");
  document.getElementById("close-panel").onclick = () => {
    panel.classList.remove("open"); selected = null; draw();
  };
  draw();
}

/* ---------------- interaction ---------------- */
function hitTest(px, py) {
  const w = s2w(px, py);
  let best = null, bestD = 1e9;
  for (const n of nodes) {
    if (!nodeVisible(n)) continue;
    const d = Math.hypot(n.x - w.x, n.y - w.y);
    const tol = nodeRadius(n) / view.scale + 6 / view.scale;
    if (d < tol && d < bestD) { best = n; bestD = d; }
  }
  return best;
}
let panning = false, moved = 0, last = null;
canvas.addEventListener("pointerdown", ev => {
  canvas.setPointerCapture(ev.pointerId);
  const r = canvas.getBoundingClientRect();
  const px = ev.clientX - r.left, py = ev.clientY - r.top;
  dragged = hitTest(px, py);
  panning = !dragged;
  moved = 0; last = { px, py };
  canvas.style.cursor = dragged ? "pointer" : "grabbing";
});
canvas.addEventListener("pointermove", ev => {
  const r = canvas.getBoundingClientRect();
  const px = ev.clientX - r.left, py = ev.clientY - r.top;
  if (dragged) {
    const w = s2w(px, py);
    dragged.x = w.x; dragged.y = w.y; dragged.vx = dragged.vy = 0;
    moved += Math.abs(px - last.px) + Math.abs(py - last.py);
    draw();
  } else if (panning && last) {
    view.cx -= (px - last.px) / view.scale;
    view.cy -= (py - last.py) / view.scale;
    moved += Math.abs(px - last.px) + Math.abs(py - last.py);
    draw();
  } else {
    const h = hitTest(px, py);
    if (h !== hovered) { hovered = h; draw(); }
    canvas.style.cursor = h ? "pointer" : "grab";
  }
  last = { px, py };
});
canvas.addEventListener("pointerup", ev => {
  const wasClick = moved < 5;
  const n = dragged;
  dragged = null; panning = false; last = null;
  canvas.style.cursor = "grab";
  if (wasClick) {
    if (n) select(n, false);
    else { panel.classList.remove("open"); selected = null; draw(); }
  }
});
canvas.addEventListener("wheel", ev => {
  ev.preventDefault();
  const r = canvas.getBoundingClientRect();
  const px = ev.clientX - r.left, py = ev.clientY - r.top;
  const before = s2w(px, py);
  view.scale = Math.min(8, Math.max(0.15, view.scale * Math.exp(-ev.deltaY * 0.0015)));
  const after = s2w(px, py);
  view.cx += before.x - after.x; view.cy += before.y - after.y;
  draw();
}, { passive: false });

/* ---------------- search + orphan toggle ---------------- */
searchBox.addEventListener("input", () => {
  const q = searchBox.value.trim().toLowerCase();
  for (const n of nodes) {
    n.match = !q || (n.id + "\\n" + n.title + "\\n" + (n.tags || []).join(" ")).toLowerCase().includes(q);
  }
  draw();
});
searchBox.addEventListener("keydown", ev => {
  if (ev.key === "Enter") {
    const hit = nodes.find(n => n.match && !n.ghost && nodeVisible(n));
    if (hit) select(hit, true);
  }
});
orphanBox.addEventListener("change", draw);

/* ---------------- boot ---------------- */
window.addEventListener("resize", () => { resize(); draw(); });
resize();
layout();
fitView();
draw();
</script>
</body>
</html>
"""


def render_html(bundle_root: str | Path, output: str | Path) -> Path:
    """Render *bundle_root* as a self-contained interactive graph at *output*.

    Reads every concept via :meth:`Bundle.load`, builds the node/edge model
    (edges from markdown links in bodies; dead links flagged), and writes a
    single ``viz.html`` file with all CSS and JavaScript inlined — no CDN, no
    network. Returns the output :class:`Path`.
    """
    bundle = Bundle.load(bundle_root)
    model = _build_model(bundle)

    data_json = json.dumps(model, ensure_ascii=False, separators=(",", ":"))
    # Never allow a literal </script> inside the embedded JSON payload.
    data_json = data_json.replace("</", "<\\/")

    dead = sum(1 for e in model["edges"] if e["dead"])
    stats = (
        f"{len(model['nodes'])} concepts &middot; {len(model['edges'])} links"
        + (f" &middot; {dead} dead link{'s' if dead != 1 else ''}" if dead else "")
    )
    title = html.escape(Path(bundle_root).name or "bundle")

    page = (
        _HTML_TEMPLATE.replace("__BUNDLE_JSON__", data_json)
        .replace("__TITLE__", title)
        .replace("__STATS__", stats)
    )

    out = Path(output)
    if out.parent != Path("."):
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out
