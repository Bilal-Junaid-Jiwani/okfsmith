/* okfsmith dashboard — vanilla SPA. 100% offline. No innerHTML with API data:
   all API-derived strings go through textContent (see el()). */
'use strict';

/* ============================== icons (trusted, static SVG) ============================== */
const ICONS = {
  overview: '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/></svg>',
  ingest: '<svg viewBox="0 0 24 24"><path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><path d="M4 19h16"/></svg>',
  explore: '<svg viewBox="0 0 24 24"><circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="7" r="2.5"/><circle cx="12" cy="17" r="2.5"/><path d="M8.3 7l7.2-.7M7.3 8.2l3.4 6.4M16.7 9.2l-3.2 5.6"/></svg>',
  temporal: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3.5 2"/></svg>',
  chat: '<svg viewBox="0 0 24 24"><path d="M21 12a8 8 0 0 1-8 8H4l2-3a8 8 0 1 1 15-5z"/><path d="M8.5 12h.01M12 12h.01M15.5 12h.01"/></svg>',
  validate: '<svg viewBox="0 0 24 24"><path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z"/><path d="M9 12l2 2 4-4.5"/></svg>',
  mcp: '<svg viewBox="0 0 24 24"><rect x="8" y="8" width="8" height="8" rx="1.5"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/></svg>',
  eval: '<svg viewBox="0 0 24 24"><path d="M4 20V10M10 20V4M16 20v-8M22 20H2"/></svg>',
  doctor: '<svg viewBox="0 0 24 24"><path d="M9 3h6v4l4 11a2.4 2.4 0 0 1-2.4 3H7.4A2.4 2.4 0 0 1 5 18L9 7z"/><path d="M7.5 14h9"/></svg>',
  settings: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.14-1.4l2-1.55-2-3.46-2.36.95a7 7 0 0 0-2.42-1.4L13.7 2.6h-3.4l-.38 2.54a7 7 0 0 0-2.42 1.4l-2.36-.95-2 3.46 2 1.55a7 7 0 0 0 0 2.8l-2 1.55 2 3.46 2.36-.95a7 7 0 0 0 2.42 1.4l.38 2.54h3.4l.38-2.54a7 7 0 0 0 2.42-1.4l2.36.95 2-3.46-2-1.55c.1-.46.14-.93.14-1.4z"/></svg>',
  search: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>',
  empty: '<svg viewBox="0 0 24 24"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
  close: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  bolt: '<svg viewBox="0 0 24 24"><path d="M13 2L4 14h6l-1 8 9-12h-6z"/></svg>',
  refresh: '<svg viewBox="0 0 24 24"><path d="M20 12a8 8 0 1 1-2.34-5.66"/><path d="M20 4v5h-5"/></svg>',
};

/* ============================== safe DOM builder ============================== */
function el(tag, attrs, ...kids) {
  const n = document.createElement(tag);
  attrs = attrs || {};
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null) continue;
    if (k === 'class') n.className = v;
    else if (k === 'text') n.textContent = v;
    else if (k === 'icon') n.innerHTML = ICONS[v] || '';   // trusted static icons only
    else if (k.startsWith('on') && typeof v === 'function') n.addEventListener(k.slice(2), v);
    else if (k === 'value') n.value = v;
    else if (k === 'checked') n.checked = !!v;
    else if (k === 'disabled') n.disabled = !!v;
    else if (k === 'selected') n.selected = !!v;
    else n.setAttribute(k, v);
  }
  for (const kid of kids.flat(9)) {
    if (kid === undefined || kid === null || kid === false) continue;
    n.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return n;
}

/* ============================== state ============================== */
const state = {
  token: null,
  expired: false,
  bundles: [],
  bundleId: sessionStorage.getItem('okf-bundle') || '',
  version: null,
  serverOk: false,
  timers: [],
  sseAbort: null,
  chat: { sessionId: null, bundleId: null, provider: null, asOf: null, busy: false },
  chatAsOf: null, // preset from temporal page
};

function clearTimers() {
  for (const t of state.timers) { clearInterval(t); clearTimeout(t); }
  state.timers = [];
  if (state.sseAbort) { state.sseAbort.abort(); state.sseAbort = null; }
}

/* ============================== toasts ============================== */
function toast(msg, kind) {
  const wrap = document.getElementById('toasts');
  const t = el('div', { class: 'toast' + (kind ? ' ' + kind : ''), text: msg });
  wrap.append(t);
  setTimeout(() => {
    t.classList.add('out');
    setTimeout(() => t.remove(), 350);
  }, 4200);
}

/* ============================== API client ============================== */
const API = '/api/v1';

function onExpired() {
  if (state.expired) return;
  state.expired = true;
  document.getElementById('expired-banner').hidden = false;
  const dot = document.getElementById('status-dot');
  dot.className = 'dot dot-red';
  document.getElementById('status-text').textContent = 'session expired';
  toast('Session expired — relaunch the dashboard for a fresh token.', 'error');
}

async function api(path, opts) {
  opts = opts || {};
  if (state.expired) throw Object.assign(new Error('Session expired'), { code: 401 });
  const headers = { Authorization: 'Bearer ' + state.token };
  const init = { method: opts.method || 'GET', headers };
  if (opts.signal) init.signal = opts.signal;
  if (opts.json !== undefined) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(opts.json);
  } else if (opts.form) {
    init.body = opts.form; // multipart; browser sets boundary
  }
  let res;
  try {
    res = await fetch(API + path, init);
  } catch (e) {
    throw Object.assign(new Error('Network error — is the server still running?'), { code: 'net' });
  }
  if (res.status === 401) {
    onExpired();
    throw Object.assign(new Error('Session expired'), { code: 401 });
  }
  const ct = res.headers.get('content-type') || '';
  let data = null;
  try { data = ct.includes('application/json') ? await res.json() : await res.text(); } catch (e) { /* empty body */ }
  if (!res.ok) {
    const err = new Error((data && data.message) || ('Request failed (HTTP ' + res.status + ')'));
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

/* SSE over fetch (EventSource cannot send Authorization headers) */
async function openSSE(path, onEvent) {
  const ctrl = new AbortController();
  state.sseAbort = ctrl;
  let res;
  try {
    res = await fetch(API + path, {
      headers: { Authorization: 'Bearer ' + state.token, Accept: 'text/event-stream' },
      signal: ctrl.signal,
    });
  } catch (e) {
    if (e.name !== 'AbortError') onEvent({ __streamError: true, message: 'Stream connection failed' });
    return;
  }
  if (res.status === 401) { onExpired(); onEvent({ __streamError: true, message: 'Unauthorized' }); return; }
  if (!res.ok || !res.body) { onEvent({ __streamError: true, message: 'Stream failed (HTTP ' + res.status + ')' }); return; }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const chunk = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        for (const line of chunk.split('\n')) {
          if (line.startsWith('data:')) {
            const payload = line.slice(5).trim();
            if (!payload) continue;
            try { onEvent(JSON.parse(payload)); } catch (e) { /* ignore malformed */ }
          }
        }
      }
    }
  } catch (e) {
    if (e.name !== 'AbortError') onEvent({ __streamError: true, message: 'Stream interrupted' });
  }
}

/* ============================== formatting helpers ============================== */
function fmtBytes(n) {
  if (n === null || n === undefined) return '–';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let v = Number(n), i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return v.toFixed(v >= 100 || i === 0 ? 0 : 1) + ' ' + units[i];
}

function fmtTime(iso) {
  if (!iso) return '–';
  const d = new Date(iso);
  return isNaN(d) ? '–' : d.toLocaleString();
}

function timeAgo(iso) {
  if (!iso) return '–';
  const d = new Date(iso);
  if (isNaN(d)) return '–';
  const s = Math.floor((Date.now() - d.getTime()) / 1000);
  if (s < 60) return 'just now';
  const m = Math.floor(s / 60);
  if (m < 60) return m + 'm ago';
  const h = Math.floor(m / 60);
  if (h < 24) return h + 'h ago';
  const days = Math.floor(h / 24);
  return days + 'd ago';
}

function shortId(id) { return id ? String(id).slice(0, 8) : '–'; }

function statusPill(status) {
  const s = String(status || 'unknown').toLowerCase();
  const cls = /^(done|ok|pass|success|complete|completed)$/.test(s) ? 'pill-green'
    : /^(running|in_progress|started|pending|queued)$/.test(s) ? 'pill-blue'
    : /^(warn|warning|stale)$/.test(s) ? 'pill-amber'
    : /^(fail|failed|error|never)$/.test(s) ? (/^never$/.test(s) ? 'pill-muted' : 'pill-red')
    : 'pill-muted';
  return el('span', { class: 'pill ' + cls, text: String(status || 'unknown') });
}

function tierPill(tier) {
  const t = String(tier || 'unknown').toLowerCase();
  const cls = t === 'high' ? 'pill-green' : t === 'medium' ? 'pill-amber' : t === 'low' ? 'pill-red' : 'pill-muted';
  return el('span', { class: 'pill ' + cls, text: 'tier: ' + String(tier || 'unknown') });
}

function scoreColor(v) {
  v = Number(v);
  if (isNaN(v)) return 'var(--muted)';
  return v >= 0.75 ? 'var(--green)' : v >= 0.5 ? 'var(--amber)' : 'var(--red)';
}

/* ============================== shared components ============================== */
function pageHead(title, sub) {
  const h = el('div', { class: 'page-head' }, el('h1', { text: title }));
  if (sub) h.append(el('p', { text: sub }));
  return h;
}

function emptyState(icon, title, body, actionLabel, actionHref) {
  const box = el('div', { class: 'empty' },
    el('div', { class: 'empty-icon', icon: icon || 'empty' }),
    el('h3', { text: title }),
    el('p', { text: body }));
  if (actionLabel && actionHref) {
    box.append(el('a', { class: 'btn btn-primary', href: actionHref, text: actionLabel }));
  }
  return box;
}

function skeletonBlock(lines) {
  const d = el('div', { class: 'card' });
  for (let i = 0; i < (lines || 4); i++) {
    d.append(el('div', { class: 'skel', style: 'height:14px;margin:10px 0;width:' + (i === 0 ? '45%' : (92 - i * 7) + '%') }));
  }
  return d;
}

function tabs(items) {
  // items: [{id, label}]
  const bar = el('div', { class: 'tabs', role: 'tablist' });
  const btns = {};
  for (const it of items) {
    const b = el('button', { class: 'tab', role: 'tab', text: it.label, onclick: () => setActive(it.id) });
    btns[it.id] = b;
    bar.append(b);
  }
  function setActive(id) {
    for (const [k, b] of Object.entries(btns)) b.classList.toggle('active', k === id);
    for (const it of items) it.onShow(it.id === id);
  }
  return { bar, setActive };
}

function openModal(title, bodyNode) {
  const root = document.getElementById('modal-root');
  root.innerHTML = '';
  const closeBtn = el('button', { class: 'btn btn-ghost btn-sm modal-close', 'aria-label': 'Close', icon: 'close' });
  const modal = el('div', { class: 'modal', role: 'dialog', 'aria-modal': 'true' }, closeBtn, el('h2', { text: title }), bodyNode);
  const backdrop = el('div', { class: 'modal-backdrop' }, modal);
  function close() { root.innerHTML = ''; document.removeEventListener('keydown', onKey); }
  function onKey(e) { if (e.key === 'Escape') close(); }
  closeBtn.addEventListener('click', close);
  backdrop.addEventListener('click', (e) => { if (e.target === backdrop) close(); });
  document.addEventListener('keydown', onKey);
  root.append(backdrop);
  return close;
}

async function conceptDetailBody(bundleId, conceptId) {
  const wrap = el('div', null, skeletonBlock(5));
  try {
    const c = await api('/bundles/' + encodeURIComponent(bundleId) + '/concepts/' + encodeURIComponent(conceptId));
    wrap.innerHTML = '';
    wrap.append(
      el('div', { class: 'dp-meta' }, tierPill(c.tier)),
      el('div', { class: 'dp-section-label', text: 'Sources' }),
      c.sources && c.sources.length
        ? el('div', { class: 'dp-sources' }, c.sources.map((s) => el('span', { class: 'src-chip', text: s })))
        : el('div', { class: 'muted small', text: 'No sources listed.' }),
      el('div', { class: 'dp-section-label', text: 'Body' }),
      el('div', { class: 'dp-body full', text: c.body || '(empty body)' })
    );
  } catch (e) {
    wrap.innerHTML = '';
    wrap.append(el('div', { class: 'muted', text: 'Could not load concept: ' + e.message }));
  }
  return wrap;
}

function openConceptModal(bundleId, conceptId, title) {
  // conceptDetailBody is async: open the modal immediately with a skeleton
  // slot, then swap in the loaded content (never render the raw Promise).
  const slot = el('div', null, skeletonBlock(5));
  openModal(title || 'Concept', slot);
  conceptDetailBody(bundleId, conceptId).then((node) => { slot.replaceWith(node); });
}

function requireBundle(view, pageName) {
  const b = state.bundles.find((x) => x.id === state.bundleId);
  if (!b) {
    view.append(emptyState('empty', 'No bundle selected',
      state.bundles.length
        ? 'Pick a bundle from the selector in the top bar to use ' + pageName + '.'
        : 'No bundles yet — ingest a document to begin.',
      state.bundles.length ? null : '#/ingest', state.bundles.length ? null : '#/ingest'));
    return null;
  }
  return b;
}

/* ============================== topbar / boot ============================== */
async function refreshHealth() {
  try {
    const h = await fetch(API + '/health').then((r) => r.json());
    state.version = h.version || '–';
    state.serverOk = h.status === 'ok';
    document.getElementById('version-badge').textContent = 'v' + state.version;
    const dot = document.getElementById('status-dot');
    dot.className = 'dot ' + (state.serverOk ? 'dot-green' : 'dot-red');
    document.getElementById('status-text').textContent = state.serverOk ? 'online' : 'unhealthy';
  } catch (e) {
    state.serverOk = false;
    document.getElementById('status-dot').className = 'dot dot-red';
    document.getElementById('status-text').textContent = 'unreachable';
  }
}

async function loadBundles() {
  const sel = document.getElementById('bundle-select');
  try {
    const data = await api('/bundles');
    state.bundles = data.bundles || [];
  } catch (e) {
    sel.innerHTML = '';
    sel.append(el('option', { value: '', text: 'Failed to load' }));
    return;
  }
  sel.innerHTML = '';
  if (!state.bundles.length) {
    sel.append(el('option', { value: '', text: 'No bundles yet' }));
    state.bundleId = '';
    return;
  }
  for (const b of state.bundles) {
    sel.append(el('option', { value: b.id, text: b.name + ' (' + (b.concepts || 0) + ' concepts)', selected: b.id === state.bundleId }));
  }
  if (!state.bundles.find((b) => b.id === state.bundleId)) {
    state.bundleId = state.bundles[0].id;
    sel.value = state.bundleId;
    sessionStorage.setItem('okf-bundle', state.bundleId);
  }
  sel.onchange = () => {
    state.bundleId = sel.value;
    sessionStorage.setItem('okf-bundle', state.bundleId);
    navigate();
  };
}

function boot() {
  // Token: read ONCE from ?token=, stash in sessionStorage, scrub URL.
  const params = new URLSearchParams(location.search);
  const q = params.get('token');
  if (q) {
    sessionStorage.setItem('okf-token', q);
    history.replaceState(null, '', location.pathname + location.hash);
  }
  state.token = sessionStorage.getItem('okf-token');
  if (!state.token) {
    document.getElementById('view').append(
      emptyState('empty', 'No session token',
        'This dashboard needs a launch token. Run `okfsmith dashboard` and open the printed URL.'));
    return;
  }
  for (const ic of document.querySelectorAll('.nav-icon[data-icon]')) {
    ic.innerHTML = ICONS[ic.dataset.icon] || '';
  }
  refreshHealth();
  state.timers.push(setInterval(refreshHealth, 30000));
  loadBundles().then(() => {
    window.addEventListener('hashchange', navigate);
    if (!location.hash) location.hash = '#/overview';
    navigate();
  });
}

document.addEventListener('DOMContentLoaded', boot);

/* ============================== router ============================== */
const ROUTES = {};
function currentRoute() {
  const h = (location.hash || '').replace(/^#\/?/, '').split('?')[0].split('/')[0];
  return ROUTES[h] ? h : 'overview';
}
function navigate() {
  clearTimers();
  const route = currentRoute();
  document.querySelectorAll('.nav-item').forEach((a) =>
    a.classList.toggle('active', a.dataset.route === route));
  const view = document.getElementById('view');
  view.innerHTML = '';
  view.focus({ preventScroll: true });
  try { ROUTES[route](view); } catch (e) {
    view.append(el('div', { class: 'empty' }, el('h3', { text: 'Page error' }), el('p', { text: e.message })));
  }
}

/* ============================== page: overview ============================== */
ROUTES.overview = async function (view) {
  view.append(pageHead('Overview', 'Bundle health at a glance.'));
  const grid = el('div', { class: 'grid grid-4 mb' });
  for (let i = 0; i < 4; i++) {
    grid.append(el('div', { class: 'card stat-card' },
      el('div', { class: 'skel', style: 'height:34px;width:60%' }),
      el('div', { class: 'skel', style: 'height:14px;width:80%;margin-top:8px' })));
  }
  view.append(grid);
  const lower = el('div', { class: 'grid grid-2' });
  const tierCard = el('div', { class: 'card' }, el('h3', { text: 'Trust tiers' }), skeletonBlock(3));
  const actCard = el('div', { class: 'card' }, el('h3', { text: 'Recent activity' }), skeletonBlock(4));
  lower.append(tierCard, actCard);
  view.append(lower);

  let bundles = [], activity = [];
  try { bundles = (await api('/bundles')).bundles || []; } catch (e) { /* keep empty */ }
  try { activity = (await api('/activity?limit=20')).items || []; } catch (e) { /* keep empty */ }
  state.bundles = bundles;
  await loadBundles();

  grid.innerHTML = '';
  const totals = bundles.reduce((acc, b) => ({
    concepts: acc.concepts + (b.concepts || 0),
    sources: acc.sources + (b.sources || 0),
    size: acc.size + (b.size_bytes || 0),
  }), { concepts: 0, sources: 0, size: 0 });
  const stats = [
    ['Bundles', String(bundles.length), false],
    ['Concepts', totals.concepts.toLocaleString(), true],
    ['Sources', totals.sources.toLocaleString(), false],
    ['Storage', fmtBytes(totals.size), false],
  ];
  for (const [label, value, accent] of stats) {
    grid.append(el('div', { class: 'card stat-card' },
      el('div', { class: 'stat-value' + (accent ? ' stat-accent' : ''), text: value }),
      el('div', { class: 'stat-label', text: label })));
  }

  tierCard.innerHTML = '';
  tierCard.append(el('h3', { text: 'Trust tiers', }, el('span', { class: 'sub', text: 'across all bundles' })));
  const tiers = bundles.reduce((acc, b) => {
    const t = b.trust_tiers || {};
    return { high: acc.high + (t.high || 0), medium: acc.medium + (t.medium || 0), low: acc.low + (t.low || 0) };
  }, { high: 0, medium: 0, low: 0 });
  const total = tiers.high + tiers.medium + tiers.low;
  if (!total) {
    tierCard.append(emptyState('empty', 'No tier data', 'Tiers appear once bundles contain concepts.'));
  } else {
    const bar = el('div', { class: 'tier-bar' });
    const colors = { high: 'var(--green)', medium: 'var(--amber)', low: 'var(--red)' };
    for (const k of ['high', 'medium', 'low']) {
      const pct = (tiers[k] / total) * 100;
      if (pct > 0) bar.append(el('span', { style: 'width:' + pct.toFixed(1) + '%;background:' + colors[k], title: k + ': ' + tiers[k] }));
    }
    tierCard.append(bar);
    const legend = el('div', { class: 'tier-legend' });
    for (const k of ['high', 'medium', 'low']) {
      legend.append(el('span', null,
        el('span', { class: 'sw', style: 'background:' + colors[k] }),
        k + ': ' + tiers[k].toLocaleString()));
    }
    tierCard.append(legend);
  }

  actCard.innerHTML = '';
  actCard.append(el('h3', { text: 'Recent activity' }));
  if (!activity.length) {
    actCard.append(el('div', { class: 'muted', text: 'Nothing logged yet.' }));
  } else {
    const feed = el('div', { class: 'activity-feed' });
    for (const item of activity) {
      feed.append(el('div', { class: 'activity-item' },
        el('span', { class: 'activity-time', text: timeAgo(item.ts), title: fmtTime(item.ts) }),
        el('span', { class: 'activity-kind' }, statusPill(item.kind)),
        el('span', { class: 'activity-msg', text: item.message })));
    }
    actCard.append(feed);
  }
};

/* ============================== page: ingest ============================== */
const INGEST_STEPS = ['parse', 'chunk', 'embed', 'validate', 'index'];

ROUTES.ingest = function (view) {
  view.append(pageHead('Ingest', 'Add documents to a bundle. Real pipeline — parse → chunk → embed → validate → index.'));
  const tabNew = el('div');
  const tabSrc = el('div');
  const t = tabs([
    { id: 'new', label: 'New ingest', onShow: (on) => { tabNew.hidden = !on; } },
    { id: 'sources', label: 'Sources & sync', onShow: (on) => { tabSrc.hidden = !on; if (on) renderSourcesTab(tabSrc); } },
  ]);
  view.append(t.bar, tabNew, tabSrc);
  renderNewIngestTab(tabNew);
  t.setActive('new');
};

function renderNewIngestTab(root) {
  root.innerHTML = '';
  const bundle = state.bundles.find((b) => b.id === state.bundleId);

  // bundle target
  const bundleField = el('div', { class: 'form-field' }, el('label', { text: 'Target bundle' }));
  const useExisting = el('select', { class: 'select' });
  if (state.bundles.length) {
    for (const b of state.bundles) useExisting.append(el('option', { value: b.id, text: b.name, selected: b.id === state.bundleId }));
  } else {
    useExisting.append(el('option', { value: '', text: 'No bundles yet — create one below' }));
    useExisting.disabled = true;
  }
  bundleField.append(useExisting);
  const newBundleField = el('div', { class: 'form-field' },
    el('label', { text: '…or new bundle name' }),
    el('input', { class: 'input', type: 'text', placeholder: 'e.g. project-docs', id: 'new-bundle-name' }));
  root.append(el('div', { class: 'form-row' }, bundleField, newBundleField));

  // options
  const kindSel = el('select', { class: 'select' });
  for (const [v, l] of [['auto', 'Auto-detect'], ['pdf', 'PDF'], ['markdown', 'Markdown'], ['wiki', 'Wiki']]) {
    kindSel.append(el('option', { value: v, text: l }));
  }
  const chunkInput = el('input', { class: 'input', type: 'number', min: '1', placeholder: 'Default' });
  const dryToggle = el('input', { type: 'checkbox', id: 'dry-run' });
  root.append(el('div', { class: 'form-row' },
    el('div', { class: 'form-field' }, el('label', { text: 'Source kind' }), kindSel),
    el('div', { class: 'form-field' },
      el('label', { text: 'Chunk size' }, el('span', { class: 'hint', text: ' optional, characters' })),
      chunkInput),
    el('div', { class: 'form-field', style: 'justify-content:flex-end' },
      el('label', { class: 'toggle' }, dryToggle, el('span', { class: 'track' }), el('span', { class: 'toggle-label', text: 'Dry run (preview only)' })))));

  // dropzone
  const dz = el('div', { class: 'dropzone', tabindex: '0', role: 'button', 'aria-label': 'Choose files to ingest' },
    el('div', { class: 'dz-title', text: 'Drag & drop files here' }),
    el('div', { class: 'dz-sub', text: 'PDF or Markdown · up to 100 MB per file · or click to browse' }));
  const fileInput = el('input', { type: 'file', multiple: true, accept: '.pdf,.md,.markdown,.txt', style: 'display:none' });
  const fileList = el('div', { class: 'mt' });
  let files = [];
  function renderFiles() {
    fileList.innerHTML = '';
    for (const f of files) {
      const chip = el('span', { class: 'file-chip' }, el('span', { text: f.name + ' (' + fmtBytes(f.size) + ')' }));
      const rm = el('button', { text: '×', 'aria-label': 'Remove ' + f.name });
      rm.onclick = () => { files = files.filter((x) => x !== f); renderFiles(); };
      chip.append(rm);
      fileList.append(chip);
    }
  }
  function addFiles(list) {
    for (const f of list) {
      if (f.size > 100 * 1024 * 1024) { toast('"' + f.name + '" exceeds the 100 MB cap and was skipped.', 'error'); continue; }
      if (!files.find((x) => x.name === f.name && x.size === f.size)) files.push(f);
    }
    renderFiles();
  }
  dz.onclick = () => fileInput.click();
  dz.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); } };
  fileInput.onchange = () => { addFiles(fileInput.files); fileInput.value = ''; };
  ['dragenter', 'dragover'].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add('dragover'); }));
  ['dragleave', 'drop'].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove('dragover'); }));
  dz.addEventListener('drop', (e) => addFiles(e.dataTransfer.files));
  root.append(dz, fileInput, fileList);

  const uploadBtn = el('button', { class: 'btn btn-primary mt', text: 'Start ingest' });
  const pipeWrap = el('div', { class: 'mt' });
  const reportWrap = el('div');
  root.append(uploadBtn, pipeWrap, reportWrap);

  function renderPipeline(stepStates) {
    // stepStates: {name: {state, detail}}
    pipeWrap.innerHTML = '';
    const pipe = el('div', { class: 'pipeline', role: 'status', 'aria-label': 'Ingest pipeline' });
    for (const name of INGEST_STEPS) {
      const s = (stepStates && stepStates[name]) || { state: 'pending', detail: '' };
      pipe.append(el('div', { class: 'pipe-step', 'data-state': s.state },
        el('div', { class: 'step-dot' }),
        el('div', { class: 'step-name', text: name }),
        el('div', { class: 'step-detail', text: s.detail || '' })));
    }
    pipeWrap.append(pipe);
  }
  renderPipeline(null);

  uploadBtn.onclick = async () => {
    if (!files.length) { toast('Choose at least one file first.', 'error'); return; }
    const newName = document.getElementById('new-bundle-name').value.trim();
    const bid = newName ? null : (useExisting.value || null);
    if (!newName && !bid) { toast('Pick a bundle or enter a new bundle name.', 'error'); return; }
    const form = new FormData();
    for (const f of files) form.append('files[]', f, f.name);
    if (bid) form.append('bundle_id', bid); else form.append('new_bundle', newName);
    form.append('source_kind', kindSel.value);
    form.append('dry_run', dryToggle.checked ? 'true' : 'false');
    const cs = parseInt(chunkInput.value, 10);
    if (!isNaN(cs) && cs > 0) form.append('chunk_size', String(cs));

    uploadBtn.disabled = true;
    renderPipeline(null);
    reportWrap.innerHTML = '';
    let jobId;
    try {
      const r = await api('/ingest', { method: 'POST', form });
      jobId = r.job_id;
      toast('Ingest job started' + (dryToggle.checked ? ' (dry run)' : '') + '.', 'success');
    } catch (e) {
      toast('Upload failed: ' + e.message, 'error');
      uploadBtn.disabled = false;
      return;
    }
    const steps = {};
    for (const n of INGEST_STEPS) steps[n] = { state: 'pending', detail: '' };
    renderPipeline(steps);
    // seed from job detail if available
    try {
      const job = await api('/ingest/jobs/' + encodeURIComponent(jobId));
      for (const s of (job.steps || [])) if (steps[s.name]) steps[s.name] = { state: s.state, detail: s.detail || '' };
      renderPipeline(steps);
    } catch (e) { /* SSE will fill in */ }
    openSSE('/ingest/jobs/' + encodeURIComponent(jobId) + '/events', (ev) => {
      if (ev.__streamError) { toast('Live updates lost: ' + ev.message, 'error'); return; }
      if (ev.step && steps[ev.step]) {
        steps[ev.step] = { state: ev.state, detail: ev.detail || '' };
        renderPipeline(steps);
      }
      if (ev.status) {
        uploadBtn.disabled = false;
        if (ev.status === 'done') {
          toast('Ingest finished.', 'success');
          // fetch final detail for dry-run report
          api('/ingest/jobs/' + encodeURIComponent(jobId)).then((job) => {
            for (const s of (job.steps || [])) if (steps[s.name]) steps[s.name] = { state: s.state, detail: s.detail || '' };
            renderPipeline(steps);
            if (job.dry_run_report) renderDryRunReport(reportWrap, job.dry_run_report);
            refreshJobHistory(historyWrap);
            loadBundles();
          }).catch(() => {});
        } else {
          toast('Ingest failed — see job history for the error.', 'error');
          refreshJobHistory(historyWrap);
        }
      }
    });
  };

  root.append(el('h2', { class: 'section-title', text: 'Job history' }));
  const historyWrap = el('div');
  root.append(historyWrap);
  refreshJobHistory(historyWrap);
};

function renderDryRunReport(wrap, report) {
  wrap.innerHTML = '';
  const box = el('div', { class: 'report-box' },
    el('h3', { text: 'Dry-run report ', }, el('span', { class: 'sub', text: '— nothing was written' })),
    el('div', { class: 'report-kpis' },
      el('div', { class: 'kpi' }, el('b', { text: String(report.would_create ?? '–') }), el('span', { text: 'would create' })),
      el('div', { class: 'kpi' }, el('b', { text: String(report.would_update ?? '–') }), el('span', { text: 'would update' }))));
  if (report.notes && report.notes.length) {
    const ul = el('ul', { class: 'notes' });
    for (const n of report.notes) ul.append(el('li', { text: n }));
    box.append(ul);
  }
  wrap.append(box);
}

async function refreshJobHistory(wrap) {
  wrap.innerHTML = '';
  wrap.append(skeletonBlock(3));
  let jobs = [];
  try { jobs = (await api('/ingest/jobs')).jobs || []; } catch (e) {
    wrap.innerHTML = '';
    wrap.append(el('div', { class: 'muted', text: 'Could not load job history: ' + e.message }));
    return;
  }
  wrap.innerHTML = '';
  if (!jobs.length) { wrap.append(el('div', { class: 'muted', text: 'No ingest jobs yet.' })); return; }
  const tw = el('div', { class: 'table-wrap' });
  const tb = el('tbody');
  tw.append(el('table', { class: 'data' },
    el('thead', null, el('tr', null,
      el('th', { text: 'Job' }), el('th', { text: 'File' }), el('th', { text: 'Kind' }),
      el('th', { text: 'Dry run' }), el('th', { text: 'Status' }), el('th', { text: 'Started' }), el('th', { text: 'Finished' }))),
    tb));
  for (const j of jobs) {
    tb.append(el('tr', null,
      el('td', { class: 'mono small', text: shortId(j.job_id) }),
      el('td', { text: j.filename || '–' }),
      el('td', { text: j.source_kind || '–' }),
      el('td', null, j.dry_run ? el('span', { class: 'pill pill-amber', text: 'dry run' }) : el('span', { class: 'muted', text: '–' })),
      el('td', null, statusPill(j.status)),
      el('td', { class: 'small', text: fmtTime(j.started_at) }),
      el('td', { class: 'small', text: fmtTime(j.finished_at) })));
  }
  wrap.append(tw);
}

async function renderSourcesTab(root) {
  root.innerHTML = '';
  const bundle = requireBundle(root, 'Sources & sync');
  if (!bundle) return;
  root.append(el('div', { class: 'row-between mb' },
    el('div', { class: 'muted', text: 'Per-source incremental sync for bundle "' + bundle.name + '".' }),
    el('button', { class: 'btn btn-primary btn-sm', text: 'Sync all sources', onclick: () => runSync(bundle.id, null, root) })));
  const wrap = el('div');
  root.append(wrap);
  wrap.append(skeletonBlock(4));
  let sources = [];
  try { sources = (await api('/sync/sources?bundle_id=' + encodeURIComponent(bundle.id))).sources || []; }
  catch (e) { wrap.innerHTML = ''; wrap.append(el('div', { class: 'muted', text: 'Could not load sources: ' + e.message })); return; }
  wrap.innerHTML = '';
  if (!sources.length) {
    wrap.append(emptyState('sync', 'No sources registered', 'Sources appear here after the first ingest registers them.'));
    return;
  }
  const tw = el('div', { class: 'table-wrap' });
  const tb = el('tbody');
  tw.append(el('table', { class: 'data' },
    el('thead', null, el('tr', null,
      el('th', { text: 'Name' }), el('th', { text: 'Kind' }), el('th', { text: 'Status' }),
      el('th', { text: 'Last sync' }), el('th', { text: 'Detail' }), el('th', { text: '' }))),
    tb));
  for (const s of sources) {
    const syncBtn = el('button', { class: 'btn btn-sm', text: 'Sync now' });
    syncBtn.onclick = () => runSync(bundle.id, s.name, root);
    tb.append(el('tr', null,
      el('td', { text: s.name }),
      el('td', { text: s.kind || '–' }),
      el('td', null, statusPill(s.status)),
      el('td', { class: 'small', text: s.last_sync ? fmtTime(s.last_sync) : 'never' }),
      el('td', { class: 'small muted', text: s.detail || '–' }),
      el('td', null, syncBtn)));
  }
  wrap.append(tw);
}

async function runSync(bundleId, source, root) {
  const statusLine = el('div', { class: 'mt muted', text: 'Starting sync…' });
  root.append(statusLine);
  let jobId;
  try {
    const r = await api('/sync/runs', { method: 'POST', json: { bundle_id: bundleId, source: source || null } });
    jobId = r.job_id;
  } catch (e) { statusLine.textContent = 'Sync failed to start: ' + e.message; toast('Sync failed: ' + e.message, 'error'); return; }
  toast('Sync job started.', 'success');
  const poll = async () => {
    try {
      const j = await api('/sync/runs/' + encodeURIComponent(jobId));
      statusLine.textContent = 'Sync ' + (source || 'all sources') + ': ' + j.status + (j.detail ? ' — ' + j.detail : '');
      if (!j.finished_at && (j.status === 'running' || j.status === 'queued')) {
        state.timers.push(setTimeout(poll, 2000));
      } else {
        toast(j.status === 'done' ? 'Sync finished.' : 'Sync ended: ' + j.status, j.status === 'done' ? 'success' : 'error');
        renderSourcesTab(root);
      }
    } catch (e) { statusLine.textContent = 'Sync status unavailable: ' + e.message; }
  };
  poll();
}

/* ============================== page: explore ============================== */
const TIER_COLORS = { high: '#4ade80', medium: '#fbbf24', low: '#f87171' };

ROUTES.explore = function (view) {
  view.append(pageHead('Explore', 'Knowledge graph and full-text search.'));
  const bundle = requireBundle(view, 'Explore');
  if (!bundle) return;

  // search
  const searchInput = el('input', { class: 'input', type: 'search', placeholder: 'Search concepts across bundles…  (Enter to search)', 'aria-label': 'Search concepts' });
  const scopeSel = el('select', { class: 'select', 'aria-label': 'Search scope' },
    el('option', { value: bundle.id, text: 'This bundle' }),
    el('option', { value: 'all', text: 'All bundles' }));
  const resultsWrap = el('div', { class: 'search-results' });
  view.append(el('div', { class: 'search-bar' }, searchInput, scopeSel), resultsWrap);

  searchInput.addEventListener('keydown', async (e) => {
    if (e.key !== 'Enter') return;
    const q = searchInput.value.trim();
    if (!q) return;
    resultsWrap.innerHTML = '';
    resultsWrap.append(skeletonBlock(2));
    let results = [];
    try {
      results = (await api('/search?q=' + encodeURIComponent(q) + '&bundle_id=' + encodeURIComponent(scopeSel.value) + '&limit=25')).results || [];
    } catch (err) { resultsWrap.innerHTML = ''; resultsWrap.append(el('div', { class: 'muted', text: 'Search failed: ' + err.message })); return; }
    resultsWrap.innerHTML = '';
    if (!results.length) { resultsWrap.append(el('div', { class: 'muted', text: 'No results for "' + q + '".' })); return; }
    resultsWrap.append(el('div', { class: 'muted small', text: results.length + ' result' + (results.length === 1 ? '' : 's') }));
    for (const r of results) {
      const hit = el('button', { class: 'search-hit' },
        el('div', { class: 'hit-title' }, el('span', { text: r.title }), tierPill(r.tier), el('span', { class: 'hit-score', text: Number(r.score).toFixed(3) })),
        el('div', { class: 'hit-snippet', text: r.snippet || '' }));
      hit.onclick = () => openConceptModal(r.bundle_id || bundle.id, r.concept_id, r.title);
      resultsWrap.append(hit);
    }
  });

  // graph
  const layout = el('div', { class: 'explore-layout' });
  const gwrap = el('div', { class: 'graph-wrap' });
  const canvas = el('canvas', { id: 'graph-canvas' });
  const toolbar = el('div', { class: 'graph-toolbar' },
    el('button', { class: 'btn btn-sm', text: 'Reset view', onclick: () => graph && graph.reset() }));
  const hint = el('div', { class: 'graph-hint', text: 'Drag to pan · scroll to zoom · click a node for details' });
  const truncBadge = el('span', { class: 'pill pill-amber graph-trunc', hidden: true });
  gwrap.append(canvas, toolbar, hint, truncBadge);
  const panel = el('div', { class: 'detail-panel' },
    el('h3', { text: 'Concept detail' }),
    el('div', { class: 'muted small', text: 'Click a node in the graph to inspect it.' }));
  layout.append(gwrap, panel);
  view.append(layout);

  let graph = null;
  (async () => {
    const ctx = canvas.getContext('2d');
    ctx.font = '12px sans-serif';
    ctx.fillStyle = '#9aa3b2';
    ctx.fillText('Loading graph…', 20, 30);
    let data;
    try {
      data = await api('/bundles/' + encodeURIComponent(bundle.id) + '/graph');
    } catch (e) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillText('Graph failed to load: ' + e.message, 20, 30);
      return;
    }
    const nodes = data.nodes || [], edges = data.edges || [];
    if (data.truncated) { truncBadge.hidden = false; truncBadge.textContent = 'Truncated — showing ' + nodes.length + ' nodes'; }
    if (!nodes.length) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillText('This bundle has no graph nodes yet.', 20, 30);
      return;
    }
    graph = buildGraph(canvas, nodes, edges, (node) => showConceptInPanel(panel, bundle.id, node));
  })();
};

async function showConceptInPanel(panel, bundleId, node) {
  panel.innerHTML = '';
  panel.append(el('h3', { text: 'Concept detail' }), skeletonBlock(4));
  try {
    const c = await api('/bundles/' + encodeURIComponent(bundleId) + '/concepts/' + encodeURIComponent(node.id));
    panel.innerHTML = '';
    const openFullBtn = el('button', { class: 'btn btn-sm', text: 'Open full body' });
    const bodyBox = el('div', { class: 'dp-body', text: (c.body || '(empty body)').slice(0, 600) });
    openFullBtn.onclick = () => { bodyBox.textContent = c.body || '(empty body)'; bodyBox.classList.add('full'); openFullBtn.remove(); };
    panel.append(
      el('h3', { class: 'dp-title', text: c.title }),
      el('div', { class: 'dp-meta' }, tierPill(c.tier)),
      el('div', { class: 'dp-section-label', text: 'Sources' }),
      c.sources && c.sources.length
        ? el('div', { class: 'dp-sources' }, c.sources.map((s) => el('span', { class: 'src-chip', text: s })))
        : el('div', { class: 'muted small', text: 'No sources listed.' }),
      el('div', { class: 'dp-section-label', text: 'Body' }),
      bodyBox,
      el('div', { class: 'mt' }, openFullBtn));
  } catch (e) {
    panel.innerHTML = '';
    panel.append(el('h3', { text: 'Concept detail' }), el('div', { class: 'muted', text: 'Could not load concept: ' + e.message }));
  }
}

function buildGraph(canvas, nodes, edges, onSelect) {
  // deterministic component-based layout (O(n))
  const parent = new Map();
  const find = (x) => { let p = parent.get(x); if (p === undefined) { parent.set(x, x); return x; } while (parent.get(p) !== p) { parent.set(p, parent.get(parent.get(p))); p = parent.get(p); } return p; };
  for (const n of nodes) parent.set(n.id, n.id);
  const nodeIds = new Set(nodes.map((n) => n.id));
  for (const e of edges) {
    if (!nodeIds.has(e.from) || !nodeIds.has(e.to)) continue;
    const a = find(e.from), b = find(e.to);
    if (a !== b) parent.set(a, b);
  }
  const comps = new Map();
  for (const n of nodes) {
    const r = find(n.id);
    if (!comps.has(r)) comps.set(r, []);
    comps.get(r).push(n);
  }
  const compList = [...comps.values()].sort((a, b) => b.length - a.length);
  const cols = Math.max(1, Math.ceil(Math.sqrt(compList.length)));
  const cell = 460;
  const pos = new Map();
  compList.forEach((comp, ci) => {
    const cx = (ci % cols) * cell + cell / 2, cy = Math.floor(ci / cols) * cell + cell / 2;
    const radius = Math.min(cell / 2 - 30, 46 + Math.sqrt(comp.length) * 26);
    comp.forEach((n, i) => {
      const ring = Math.floor(i / 10), slot = i % 10;
      const ang = (slot / 10) * Math.PI * 2 + ring * 0.45 + ci;
      const r = Math.min(24 + ring * 42, radius);
      pos.set(n.id, { x: cx + Math.cos(ang) * r + ((i * 37) % 13), y: cy + Math.sin(ang) * r + ((i * 53) % 13) });
    });
  });

  const view = { x: 0, y: 0, k: 1 };
  const ctx = canvas.getContext('2d');
  let hovered = null, selected = null, dragging = false, moved = false, lx = 0, ly = 0;
  let raf = 0;

  function resize() {
    const r = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, r.width * dpr);
    canvas.height = Math.max(1, 560 * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    schedule();
  }
  function w2s(p) { return { x: (p.x - view.x) * view.k, y: (p.y - view.y) * view.k }; }
  function draw() {
    raf = 0;
    const w = canvas.width / (window.devicePixelRatio || 1), h = canvas.height / (window.devicePixelRatio || 1);
    ctx.clearRect(0, 0, w, h);
    ctx.lineWidth = 1;
    ctx.strokeStyle = 'rgba(60,70,95,0.55)';
    ctx.beginPath();
    for (const e of edges) {
      const a = pos.get(e.from), b = pos.get(e.to);
      if (!a || !b) continue;
      const sa = w2s(a), sb = w2s(b);
      if (sa.x < -50 || sa.x > w + 50 || sa.y < -50 || sa.y > h + 50) continue;
      ctx.moveTo(sa.x, sa.y); ctx.lineTo(sb.x, sb.y);
    }
    ctx.stroke();
    for (const n of nodes) {
      const p = pos.get(n.id); if (!p) continue;
      const s = w2s(p);
      if (s.x < -20 || s.x > w + 20 || s.y < -20 || s.y > h + 20) continue;
      const col = TIER_COLORS[String(n.tier || '').toLowerCase()] || '#8a93a5';
      ctx.beginPath();
      ctx.arc(s.x, s.y, n === selected ? 9 : 6, 0, Math.PI * 2);
      ctx.fillStyle = col;
      ctx.fill();
      if (n === hovered || n === selected) {
        ctx.beginPath();
        ctx.arc(s.x, s.y, n === selected ? 13 : 10, 0, Math.PI * 2);
        ctx.strokeStyle = '#d97757';
        ctx.lineWidth = 2;
        ctx.stroke();
      }
      if (view.k > 1.15 || n === hovered || n === selected) {
        ctx.fillStyle = n === selected ? '#e8e6e3' : '#9aa3b2';
        ctx.font = (n === selected ? 'bold ' : '') + '11px sans-serif';
        ctx.fillText(n.label || n.id, s.x + 11, s.y + 4);
      }
    }
  }
  function schedule() { if (!raf) raf = requestAnimationFrame(draw); }

  canvas.addEventListener('mousedown', (e) => { dragging = true; moved = false; lx = e.clientX; ly = e.clientY; });
  window.addEventListener('mouseup', () => { dragging = false; });
  canvas.addEventListener('mousemove', (e) => {
    if (dragging) {
      const dx = e.clientX - lx, dy = e.clientY - ly;
      if (Math.abs(dx) + Math.abs(dy) > 2) moved = true;
      view.x -= dx / view.k; view.y -= dy / view.k;
      lx = e.clientX; ly = e.clientY;
      schedule();
    } else {
      const hit = hitTest(e);
      hovered = hit;
      canvas.style.cursor = hit ? 'pointer' : 'grab';
      schedule();
    }
  });
  canvas.addEventListener('mouseleave', () => { hovered = null; schedule(); });
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    const r = canvas.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    const k2 = Math.min(4, Math.max(0.12, view.k * (e.deltaY < 0 ? 1.12 : 1 / 1.12)));
    view.x = (mx / view.k + view.x) - mx / k2;
    view.y = (my / view.k + view.y) - my / k2;
    view.k = k2;
    schedule();
  }, { passive: false });
  canvas.addEventListener('click', (e) => {
    if (moved) return;
    const hit = hitTest(e);
    selected = hit;
    schedule();
    if (hit) onSelect(hit);
  });
  function hitTest(e) {
    const r = canvas.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    const tol = 14 / view.k;
    let best = null, bestD = tol;
    for (const n of nodes) {
      const p = pos.get(n.id); if (!p) continue;
      const d = Math.hypot(p.x - (mx / view.k + view.x), p.y - (my / view.k + view.y));
      if (d < bestD) { bestD = d; best = n; }
    }
    return best;
  }

  new ResizeObserver(resize).observe(canvas);
  resize();
  // fit all
  let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
  for (const p of pos.values()) { minX = Math.min(minX, p.x); minY = Math.min(minY, p.y); maxX = Math.max(maxX, p.x); maxY = Math.max(maxY, p.y); }
  const w0 = canvas.getBoundingClientRect().width || 800;
  view.k = Math.min(1.4, Math.max(0.12, Math.min(w0 / (maxX - minX + 120), 560 / (maxY - minY + 120))));
  view.x = minX - 40; view.y = minY - 40;
  schedule();
  return { reset() { view.k = Math.min(1.4, Math.max(0.12, Math.min(w0 / (maxX - minX + 120), 560 / (maxY - minY + 120)))); view.x = minX - 40; view.y = minY - 40; schedule(); } };
}

/* ============================== page: temporal ============================== */
ROUTES.temporal = function (view) {
  view.append(pageHead('Temporal', 'See which concepts were valid at any point in time.'));
  const bundle = requireBundle(view, 'Temporal');
  if (!bundle) return;

  const dt = el('input', { class: 'input', type: 'datetime-local' });
  const now = new Date();
  dt.value = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const loadBtn = el('button', { class: 'btn btn-primary', text: 'Load snapshot' });
  const chatBtn = el('button', { class: 'btn', text: 'Chat as of this time', disabled: true });
  const results = el('div', { class: 'mt' });
  view.append(
    el('div', { class: 'temporal-controls' },
      el('div', { class: 'form-field' }, el('label', { text: 'As of' }), dt),
      loadBtn, chatBtn),
    results);

  let currentAsOf = null;
  async function load() {
    const iso = dt.value ? new Date(dt.value).toISOString() : null;
    if (!iso) { toast('Pick a date and time.', 'error'); return; }
    currentAsOf = iso;
    chatBtn.disabled = false;
    results.innerHTML = '';
    results.append(skeletonBlock(4));
    let snap;
    try { snap = await api('/bundles/' + encodeURIComponent(bundle.id) + '/snapshot?as_of=' + encodeURIComponent(iso)); }
    catch (e) { results.innerHTML = ''; results.append(el('div', { class: 'muted', text: 'Snapshot failed: ' + e.message })); return; }
    const concepts = snap.concepts || [];
    results.innerHTML = '';
    results.append(el('div', { class: 'muted small mb', text: concepts.length + ' concepts valid at ' + fmtTime(snap.as_of || iso) }));
    if (!concepts.length) { results.append(emptyState('temporal', 'No concepts at this time', 'Nothing in this bundle was valid at the selected timestamp.')); return; }
    const tiers = { high: 0, medium: 0, low: 0 };
    for (const c of concepts) { const t = String(c.tier || '').toLowerCase(); if (tiers[t] !== undefined) tiers[t]++; }
    const bar = el('div', { class: 'tier-bar' });
    const colors = { high: 'var(--green)', medium: 'var(--amber)', low: 'var(--red)' };
    for (const k of ['high', 'medium', 'low']) if (tiers[k]) bar.append(el('span', { style: 'width:' + (tiers[k] / concepts.length * 100) + '%;background:' + colors[k], title: k + ': ' + tiers[k] }));
    results.append(bar);
    const tw = el('div', { class: 'table-wrap' });
    const tb = el('tbody');
    tw.append(el('table', { class: 'data' },
      el('thead', null, el('tr', null, el('th', { text: 'Concept' }), el('th', { text: 'Tier' }), el('th', { text: 'Valid from' }), el('th', { text: 'Valid to' }))),
      tb));
    for (const c of concepts) {
      const row = el('tr', { class: 'clickable' },
        el('td', { text: c.title }),
        el('td', null, tierPill(c.tier)),
        el('td', { class: 'validity', text: c.valid_from ? fmtTime(c.valid_from) : '–' }),
        el('td', { class: 'validity', text: c.valid_to ? fmtTime(c.valid_to) : 'present' }));
      row.onclick = () => openConceptModal(bundle.id, c.id, c.title);
      tb.append(row);
    }
    results.append(tw);
  }
  loadBtn.onclick = load;
  chatBtn.onclick = () => {
    if (!currentAsOf) return;
    state.chatAsOf = currentAsOf;
    toast('Temporal context set — chat will answer as of ' + fmtTime(currentAsOf) + '.', 'success');
    location.hash = '#/chat';
  };
  load();
};

/* ============================== page: chat ============================== */
const SLASH = ['/search', '/read', '/list', '/graph', '/validate'];

ROUTES.chat = function (view) {
  view.append(pageHead('Chat', 'Grounded answers with citations. Default is no-LLM retrieval; pick a provider preset for model-backed chat.'));
  const bundle = requireBundle(view, 'Chat');
  if (!bundle) return;

  // options row
  const provSel = el('select', { class: 'select', 'aria-label': 'Provider preset' },
    el('option', { value: '', text: 'Grounded (no LLM) — default' }));
  const asofInput = el('input', { class: 'input', type: 'datetime-local', 'aria-label': 'Answer as of time (optional)' });
  if (state.chatAsOf) {
    const d = new Date(state.chatAsOf);
    asofInput.value = new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    const note = el('span', { class: 'pill pill-accent mb', text: 'temporal preset from Temporal page — answers grounded as of ' + fmtTime(state.chatAsOf) });
    state.chatAsOf = null;
    view.append(note);
  }
  const newBtn = el('button', { class: 'btn btn-sm', text: 'New session' });
  view.append(el('div', { class: 'chat-opts' },
    el('div', { class: 'form-field' }, el('label', { text: 'Provider' }), provSel),
    el('div', { class: 'form-field' }, el('label', { text: 'As of (optional)' }), asofInput),
    el('div', { class: 'form-field', style: 'justify-content:flex-end;flex:0' }, newBtn)));

  api('/chat/providers').then((d) => {
    for (const p of (d.providers || [])) provSel.append(el('option', { value: p.id, text: p.name + (p.description ? ' — ' + p.description : '') }));
  }).catch(() => { /* providers optional; grounded mode still works */ });

  const layout = el('div', { class: 'chat-layout' });
  const thread = el('div', { class: 'chat-thread', 'aria-live': 'polite' });
  const slashRow = el('div', { class: 'chat-slash' });
  for (const s of SLASH) {
    slashRow.append(el('button', { class: 'slash-chip', text: s, title: 'Quick action: ' + s, onclick: () => runSlash(s, bundle) }));
  }
  const input = el('input', { class: 'input', type: 'text', placeholder: 'Ask about this bundle…  (try /search <query>)', 'aria-label': 'Chat message' });
  const sendBtn = el('button', { class: 'btn btn-primary', text: 'Send' });
  layout.append(thread, slashRow, el('div', { class: 'chat-input-row' }, input, sendBtn));
  view.append(layout);

  const chat = state.chat;
  function threadMsg(cls, textNode) {
    const m = el('div', { class: 'msg ' + cls }, el('div', { class: 'msg-text', text: textNode }));
    thread.append(m);
    thread.scrollTop = thread.scrollHeight;
    return m;
  }

  async function ensureSession() {
    if (chat.sessionId && chat.bundleId === bundle.id) return chat.sessionId;
    if (chat.sessionId) { try { await api('/chat/sessions/' + encodeURIComponent(chat.sessionId), { method: 'DELETE' }); } catch (e) {} }
    const asOf = asofInput.value ? new Date(asofInput.value).toISOString() : null;
    const r = await api('/chat/sessions', { method: 'POST', json: { bundle_id: bundle.id, provider: provSel.value || null, as_of: asOf } });
    chat.sessionId = r.session_id; chat.bundleId = bundle.id;
    chat.provider = provSel.value || null; chat.asOf = asOf;
    threadMsg('assistant', 'Session started on "' + bundle.name + '"' +
      (chat.provider ? ' with provider "' + provSel.selectedOptions[0].textContent.split(' — ')[0] + '"' : ' (grounded, no LLM)') +
      (asOf ? ' as of ' + fmtTime(asOf) : '') + '.');
    return chat.sessionId;
  }

  newBtn.onclick = async () => {
    if (chat.sessionId) { try { await api('/chat/sessions/' + encodeURIComponent(chat.sessionId), { method: 'DELETE' }); } catch (e) {} }
    chat.sessionId = null; chat.bundleId = null;
    thread.innerHTML = '';
    toast('Session cleared — a new one starts on your next message.', 'success');
  };

  async function send(text) {
    const msg = (text || '').trim();
    if (!msg || chat.busy) return;
    if (msg.startsWith('/')) { runSlash(msg, bundle); input.value = ''; return; }
    chat.busy = true; sendBtn.disabled = true;
    threadMsg('user', msg);
    input.value = '';
    const typing = threadMsg('assistant', '');
    typing.firstChild.append(el('span', { class: 'typing' }, el('span'), el('span'), el('span')));
    try {
      const sid = await ensureSession();
      const r = await api('/chat/sessions/' + encodeURIComponent(sid) + '/messages', { method: 'POST', json: { message: msg } });
      typing.remove();
      const m = threadMsg('assistant', r.answer || '(empty answer)');
      if (r.citations && r.citations.length) {
        const cites = el('div', { class: 'citations' });
        for (const c of r.citations) {
          const chip = el('button', { class: 'cite-chip', text: c.title || c.concept_id, title: (c.snippet || '') + '\nSources: ' + (c.sources || []).join(', ') });
          chip.onclick = () => openConceptModal(bundle.id, c.concept_id, c.title);
          cites.append(chip);
        }
        m.append(cites);
      }
    } catch (e) {
      typing.remove();
      threadMsg('assistant', 'Error: ' + e.message);
    }
    chat.busy = false; sendBtn.disabled = false;
    thread.scrollTop = thread.scrollHeight;
  }
  sendBtn.onclick = () => send(input.value);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') send(input.value); });

  async function runSlash(cmd, b) {
    const [name, ...rest] = cmd.trim().split(/\s+/);
    const arg = rest.join(' ');
    threadMsg('user', cmd.trim());
    const m = threadMsg('assistant', '');
    m.firstChild.textContent = 'Working…';
    try {
      if (name === '/search') {
        if (!arg) throw new Error('Usage: /search <query>');
        const r = await api('/search?q=' + encodeURIComponent(arg) + '&bundle_id=' + encodeURIComponent(b.id) + '&limit=10');
        const res = r.results || [];
        m.firstChild.textContent = res.length ? res.length + ' result(s) for "' + arg + '":' : 'No results for "' + arg + '".';
        const cites = el('div', { class: 'citations' });
        for (const c of res) {
          const chip = el('button', { class: 'cite-chip', text: c.title });
          chip.onclick = () => openConceptModal(c.bundle_id || b.id, c.concept_id, c.title);
          cites.append(chip);
        }
        if (res.length) m.append(cites);
      } else if (name === '/read') {
        if (!arg) throw new Error('Usage: /read <concept-id>');
        const c = await api('/bundles/' + encodeURIComponent(b.id) + '/concepts/' + encodeURIComponent(arg));
        m.firstChild.textContent = c.title + '\n\n' + (c.body || '(empty body)').slice(0, 2000);
      } else if (name === '/list') {
        const r = await api('/bundles/' + encodeURIComponent(b.id) + '/concepts?page=1&per_page=25');
        const items = r.items || [];
        m.firstChild.textContent = 'First ' + items.length + ' of ' + r.total + ' concepts:';
        const cites = el('div', { class: 'citations' });
        for (const c of items) {
          const chip = el('button', { class: 'cite-chip', text: c.title });
          chip.onclick = () => openConceptModal(b.id, c.id, c.title);
          cites.append(chip);
        }
        if (items.length) m.append(cites);
      } else if (name === '/graph') {
        m.firstChild.textContent = 'Opening the knowledge graph…';
        location.hash = '#/explore';
      } else if (name === '/validate') {
        const r = await api('/validate/runs', { method: 'POST', json: { bundle_id: b.id } });
        m.firstChild.textContent = 'Validator started (run ' + shortId(r.run_id) + '). See the Validate page for per-rule results.';
      } else {
        m.firstChild.textContent = 'Unknown command. Available: ' + SLASH.join(' ');
      }
    } catch (e) {
      m.firstChild.textContent = 'Error: ' + e.message;
    }
    thread.scrollTop = thread.scrollHeight;
  }
};

/* ============================== page: validate ============================== */
ROUTES.validate = function (view) {
  view.append(pageHead('Validate', 'Run the §11 validator against a bundle and inspect per-rule results.'));
  const bundle = requireBundle(view, 'Validate');
  if (!bundle) return;

  const runBtn = el('button', { class: 'btn btn-primary', text: 'Run validator' });
  const results = el('div', { class: 'mt' });
  view.append(el('div', { class: 'row-between mb' },
    el('div', { class: 'muted', text: 'Bundle: ' + bundle.name }),
    runBtn), results);

  runBtn.onclick = async () => {
    runBtn.disabled = true;
    results.innerHTML = '';
    results.append(skeletonBlock(4));
    let runId;
    try {
      const r = await api('/validate/runs', { method: 'POST', json: { bundle_id: bundle.id } });
      runId = r.run_id;
    } catch (e) { results.innerHTML = ''; results.append(el('div', { class: 'muted', text: 'Could not start validator: ' + e.message })); runBtn.disabled = false; return; }
    const poll = async () => {
      try {
        const r = await api('/validate/runs/' + encodeURIComponent(runId));
        renderValidateResult(results, r, bundle.id);
        if (r.status === 'running') {
          state.timers.push(setTimeout(poll, 2500));
        } else {
          runBtn.disabled = false;
          toast(r.status === 'done' ? 'Validation finished.' : 'Validation ended: ' + r.status, r.status === 'done' ? 'success' : 'error');
        }
      } catch (e) {
        results.innerHTML = '';
        results.append(el('div', { class: 'muted', text: 'Could not fetch run: ' + e.message }));
        runBtn.disabled = false;
      }
    };
    poll();
  };
};

function renderValidateResult(root, r, bundleId) {
  root.innerHTML = '';
  const s = r.summary || { pass: 0, fail: 0, warn: 0 };
  root.append(el('div', { class: 'grid grid-3 mb' },
    el('div', { class: 'card stat-card' }, el('div', { class: 'stat-value', style: 'color:var(--green)', text: String(s.pass ?? 0) }), el('div', { class: 'stat-label', text: 'Passed' })),
    el('div', { class: 'card stat-card' }, el('div', { class: 'stat-value', style: 'color:var(--amber)', text: String(s.warn ?? 0) }), el('div', { class: 'stat-label', text: 'Warnings' })),
    el('div', { class: 'card stat-card' }, el('div', { class: 'stat-value', style: 'color:var(--red)', text: String(s.fail ?? 0) }), el('div', { class: 'stat-label', text: 'Failed' }))));
  const head = el('div', { class: 'row-between mb' },
    el('h2', { class: 'section-title', style: 'margin:0', text: 'Rule results' }),
    statusPill(r.status));
  root.append(head);
  const rules = r.rules || [];
  if (!rules.length) { root.append(el('div', { class: 'muted', text: r.status === 'running' ? 'Validator is running…' : 'No rule results returned.' })); return; }
  const list = el('div', { class: 'card' });
  for (const rule of rules) {
    const st = String(rule.status || '').toLowerCase();
    const pillCls = st === 'pass' ? 'pill-green' : st === 'warn' ? 'pill-amber' : st === 'fail' ? 'pill-red' : 'pill-muted';
    const item = el('div', { class: 'rule-item' },
      el('span', { class: 'pill ' + pillCls, text: st || 'unknown' }),
      el('div', { class: 'rule-body' },
        el('div', { class: 'rule-name', text: rule.rule || 'unnamed rule' }),
        el('div', { class: 'rule-msg', text: rule.message || '' })));
    if (rule.concepts && rule.concepts.length) {
      const chips = el('div', { class: 'rule-concepts' });
      for (const cid of rule.concepts.slice(0, 12)) {
        const chip = el('button', { class: 'cite-chip', text: shortId(cid), title: cid });
        chip.onclick = () => openConceptModal(bundleId, cid, 'Concept ' + shortId(cid));
        chips.append(chip);
      }
      if (rule.concepts.length > 12) chips.append(el('span', { class: 'muted small', text: '+' + (rule.concepts.length - 12) + ' more' }));
      item.lastChild.append(chips);
    }
    list.append(item);
  }
  root.append(list);
}

/* ============================== page: mcp ============================== */
ROUTES.mcp = function (view) {
  view.append(pageHead('MCP', 'Model Context Protocol server status, tool catalog, governed write-back, and audit log.'));
  const bundle = requireBundle(view, 'MCP');
  if (!bundle) return;

  const statusCard = el('div', { class: 'card mb' }, el('h3', { text: 'Server status' }), skeletonBlock(2));
  const toolsCard = el('div', { class: 'card mb' }, el('h3', { text: 'Tool catalog' }), skeletonBlock(3));
  const writeCard = el('div', { class: 'card mb' });
  const auditCard = el('div', { class: 'card' }, el('h3', { text: 'Audit log' }), skeletonBlock(3));
  view.append(statusCard, toolsCard, writeCard, auditCard);

  api('/mcp/status').then((s) => {
    statusCard.innerHTML = '';
    statusCard.append(el('h3', { text: 'Server status' }));
    const tools = s.tools || [];
    statusCard.append(
      el('div', { class: 'row-between' },
        el('div', null,
          s.available ? el('span', { class: 'pill pill-green', text: 'available' }) : el('span', { class: 'pill pill-red', text: 'unavailable' }),
          el('span', { class: 'muted small', style: 'margin-left:10px', text: 'transport: ' + (s.transport || '–') })),
        el('button', { class: 'btn btn-sm', text: 'Refresh', onclick: () => navigate() })),
      s.detail ? el('div', { class: 'muted small mt', text: s.detail }) : null,
      tools.length ? el('div', { class: 'mt' }, el('div', { class: 'muted small mb', text: 'Tools (' + tools.length + '):' }),
        el('div', { style: 'display:flex;flex-wrap:wrap;gap:6px' }, tools.map((t) => el('span', { class: 'src-chip', text: t })))) : null);
  }).catch((e) => { statusCard.innerHTML = ''; statusCard.append(el('h3', { text: 'Server status' }), el('div', { class: 'muted', text: 'Status unavailable: ' + e.message })); });

  api('/mcp/tools').then((d) => {
    toolsCard.innerHTML = '';
    toolsCard.append(el('h3', { text: 'Tool catalog' }));
    const tools = d.tools || [];
    if (!tools.length) { toolsCard.append(el('div', { class: 'muted', text: 'No tools reported.' })); return; }
    const grid = el('div', { class: 'tool-grid' });
    for (const t of tools) {
      grid.append(el('div', { class: 'tool-card' },
        el('div', { class: 'tool-name', text: t.name }),
        el('div', { class: 'tool-desc', text: t.description || '' }),
        t.params && Object.keys(t.params).length ? el('div', { class: 'tool-params', text: 'params: ' + Object.keys(t.params).join(', ') }) : null));
    }
    toolsCard.append(grid);
  }).catch((e) => { toolsCard.innerHTML = ''; toolsCard.append(el('h3', { text: 'Tool catalog' }), el('div', { class: 'muted', text: 'Catalog unavailable: ' + e.message })); });

  // write-back flow
  writeCard.append(el('h3', { text: 'Governed write-back' }),
    el('p', { class: 'muted small', text: 'Writes are previewed first. Nothing is written until you explicitly approve.' }));
  const opSel = el('select', { class: 'select' },
    el('option', { value: 'create', text: 'create — new concept' }),
    el('option', { value: 'update', text: 'update — existing concept' }));
  const cidInput = el('input', { class: 'input', type: 'text', placeholder: 'concept id (required for update)' });
  const payloadInput = el('textarea', { class: 'textarea', placeholder: 'Payload as JSON, e.g. {"title": "...", "body": "...", "tier": "high"}' });
  const previewBtn = el('button', { class: 'btn btn-primary', text: 'Preview write' });
  const previewOut = el('div', { class: 'mt' });
  writeCard.append(
    el('div', { class: 'form-row' },
      el('div', { class: 'form-field' }, el('label', { text: 'Operation' }), opSel),
      el('div', { class: 'form-field' }, el('label', { text: 'Concept ID' }), cidInput)),
    el('div', { class: 'form-field mb' }, el('label', { text: 'Payload (JSON)' }), payloadInput),
    previewBtn, previewOut);

  previewBtn.onclick = async () => {
    let payload;
    try { payload = payloadInput.value.trim() ? JSON.parse(payloadInput.value) : {}; }
    catch (e) { toast('Payload is not valid JSON: ' + e.message, 'error'); return; }
    if (opSel.value === 'update' && !cidInput.value.trim()) { toast('Concept ID is required for update.', 'error'); return; }
    previewBtn.disabled = true;
    previewOut.innerHTML = '';
    previewOut.append(skeletonBlock(3));
    try {
      const p = await api('/mcp/preview_write', { method: 'POST', json: {
        bundle_id: bundle.id, operation: opSel.value,
        concept_id: cidInput.value.trim() || null, payload } });
      previewOut.innerHTML = '';
      previewOut.append(el('div', { class: 'muted small mb', text: 'Preview ' + shortId(p.preview_id) }));
      if (p.summary) previewOut.append(el('div', { class: 'mb', text: p.summary }));
      if (p.warnings && p.warnings.length) {
        const wl = el('div', { class: 'warn-list' }, 'Trust-tier gate warnings:');
        const ul = el('ul');
        for (const w of p.warnings) ul.append(el('li', { text: w }));
        wl.append(ul);
        previewOut.append(wl);
      }
      if (p.diff) previewOut.append(el('div', { class: 'dp-section-label', text: 'Diff' }), el('div', { class: 'diff-box', text: p.diff }));
      const approveBtn = el('button', { class: 'btn btn-danger mt', text: 'Approve & write' });
      const cancelBtn = el('button', { class: 'btn btn-ghost mt', text: 'Discard' });
      previewOut.append(el('div', { style: 'display:flex;gap:10px' }, approveBtn, cancelBtn));
      cancelBtn.onclick = () => { previewOut.innerHTML = ''; };
      approveBtn.onclick = async () => {
        approveBtn.disabled = true;
        try {
          const w = await api('/mcp/write', { method: 'POST', json: { preview_id: p.preview_id, approved: true } });
          toast('Write committed (audit ' + shortId(w.audit_id) + ').', 'success');
          previewOut.innerHTML = '';
          loadAudit();
          loadBundles();
        } catch (e) { toast('Write failed: ' + e.message, 'error'); approveBtn.disabled = false; }
      };
    } catch (e) {
      previewOut.innerHTML = '';
      previewOut.append(el('div', { class: 'muted', text: 'Preview failed: ' + e.message }));
    }
    previewBtn.disabled = false;
  };

  async function loadAudit() {
    auditCard.innerHTML = '';
    auditCard.append(el('h3', { text: 'Audit log' }), skeletonBlock(3));
    let entries = [];
    try { entries = (await api('/mcp/audit_log?limit=50')).entries || []; }
    catch (e) { auditCard.innerHTML = ''; auditCard.append(el('h3', { text: 'Audit log' }), el('div', { class: 'muted', text: 'Audit log unavailable: ' + e.message })); return; }
    auditCard.innerHTML = '';
    auditCard.append(el('h3', { text: 'Audit log' }));
    if (!entries.length) { auditCard.append(el('div', { class: 'muted', text: 'No audit entries yet.' })); return; }
    const tw = el('div', { class: 'table-wrap' });
    const tb = el('tbody');
    tw.append(el('table', { class: 'data' },
      el('thead', null, el('tr', null, el('th', { text: 'Time' }), el('th', { text: 'Actor' }), el('th', { text: 'Action' }), el('th', { text: 'Concept' }), el('th', { text: 'Detail' }))),
      tb));
    for (const en of entries) {
      tb.append(el('tr', null,
        el('td', { class: 'small', text: fmtTime(en.ts) }),
        el('td', { text: en.actor || '–' }),
        el('td', null, statusPill(en.action)),
        el('td', { class: 'mono small', text: en.concept_id ? shortId(en.concept_id) : '–' }),
        el('td', { class: 'small muted', text: en.detail || '–' })));
    }
    auditCard.append(tw);
  }
  loadAudit();
};

/* ============================== page: eval ============================== */
ROUTES.eval = function (view) {
  view.append(pageHead('Eval', 'RAG triad evaluation with CI gating.'));
  const bundle = requireBundle(view, 'Eval');
  if (!bundle) return;

  const runBtn = el('button', { class: 'btn btn-primary', text: 'Run eval' });
  const hint = el('div', { class: 'muted small', text: 'Bundle: ' + bundle.name });
  view.append(el('div', { class: 'row-between mb' }, hint, runBtn));
  const listWrap = el('div', { class: 'mb' });
  const detailWrap = el('div');
  view.append(listWrap, detailWrap);

  async function refreshList() {
    listWrap.innerHTML = '';
    listWrap.append(skeletonBlock(3));
    let runs = [];
    try { runs = (await api('/eval/runs')).runs || []; } catch (e) {
      listWrap.innerHTML = ''; listWrap.append(el('div', { class: 'muted', text: 'Could not load runs: ' + e.message })); return;
    }
    runs = runs.filter((r) => !r.bundle_id || r.bundle_id === bundle.id);
    listWrap.innerHTML = '';
    if (!runs.length) {
      listWrap.append(emptyState('eval', 'No eval runs yet', 'Run an eval to score context, groundedness, and answer relevance against the golden set.'));
      return;
    }
    const tw = el('div', { class: 'table-wrap' });
    const tb = el('tbody');
    tw.append(el('table', { class: 'data' },
      el('thead', null, el('tr', null,
        el('th', { text: 'Run' }), el('th', { text: 'Started' }), el('th', { text: 'Status' }),
        el('th', { text: 'CI gate' }), el('th', { text: 'Context' }), el('th', { text: 'Groundedness' }), el('th', { text: 'Answer rel.' }))),
      tb));
    for (const r of runs) {
      const tri = r.triad || {};
      const gate = r.ci_gate;
      const gatePill = gate === 'pass' ? el('span', { class: 'pill pill-green', text: 'pass' })
        : gate === 'fail' ? el('span', { class: 'pill pill-red', text: 'fail' })
        : el('span', { class: 'pill pill-muted', text: 'unknown' });
      const row = el('tr', { class: 'clickable' },
        el('td', { class: 'mono small', text: shortId(r.run_id) }),
        el('td', { class: 'small', text: fmtTime(r.started_at) }),
        el('td', null, statusPill(r.status)),
        el('td', null, gatePill),
        el('td', { style: 'color:' + scoreColor(tri.context), text: tri.context != null ? Number(tri.context).toFixed(3) : '–' }),
        el('td', { style: 'color:' + scoreColor(tri.groundedness), text: tri.groundedness != null ? Number(tri.groundedness).toFixed(3) : '–' }),
        el('td', { style: 'color:' + scoreColor(tri.answer_relevance), text: tri.answer_relevance != null ? Number(tri.answer_relevance).toFixed(3) : '–' }));
      row.onclick = () => showRunDetail(r.run_id);
      tb.append(row);
    }
    listWrap.append(tw);
    // keep polling while any run is non-terminal
    const active = runs.some((r) => /^(running|queued|pending|started|in_progress)$/i.test(String(r.status || '')));
    if (active) state.timers.push(setTimeout(refreshList, 4000));
  }

  async function showRunDetail(runId) {
    detailWrap.innerHTML = '';
    detailWrap.append(skeletonBlock(5));
    let r;
    try { r = await api('/eval/runs/' + encodeURIComponent(runId)); }
    catch (e) { detailWrap.innerHTML = ''; detailWrap.append(el('div', { class: 'muted', text: 'Could not load run: ' + e.message })); return; }
    detailWrap.innerHTML = '';
    detailWrap.append(el('h2', { class: 'section-title', text: 'Run ' + shortId(r.run_id) + ' ', }, statusPill(r.status)));
    const tri = r.triad || {};
    const triad = el('div', { class: 'triad' });
    for (const [key, label] of [['context', 'Context'], ['groundedness', 'Groundedness'], ['answer_relevance', 'Answer relevance']]) {
      const v = tri[key];
      triad.append(el('div', { class: 'card triad-card' },
        el('div', { class: 'score', style: 'color:' + scoreColor(v), text: v != null ? Number(v).toFixed(3) : '–' }),
        el('div', { class: 'label', text: label }),
        el('div', { class: 'score-bar' }, el('i', { style: 'width:' + (v != null ? Math.max(0, Math.min(1, v)) * 100 : 0) + '%' }))));
    }
    detailWrap.append(triad);
    if (r.ci_gate && typeof r.ci_gate === 'object') {
      const g = r.ci_gate;
      const cls = g.status === 'pass' ? 'pill-green' : g.status === 'fail' ? 'pill-red' : 'pill-muted';
      detailWrap.append(el('div', { class: 'card mb' },
        el('h3', { text: 'CI gate ', }, el('span', { class: 'pill ' + cls, text: g.status || 'unknown' })),
        g.threshold ? el('div', { class: 'muted small', text: 'Threshold: ' + g.threshold }) : null,
        g.detail ? el('div', { class: 'mt', text: g.detail }) : null));
    }
    const qs = r.questions || [];
    detailWrap.append(el('h2', { class: 'section-title', text: 'Per-question scores (' + qs.length + ')' }));
    if (!qs.length) { detailWrap.append(el('div', { class: 'muted', text: 'No question-level results.' })); return; }
    const tw = el('div', { class: 'table-wrap' });
    const tb = el('tbody');
    tw.append(el('table', { class: 'data' },
      el('thead', null, el('tr', null,
        el('th', { text: 'Question' }), el('th', { text: 'Score' }), el('th', { text: 'Context' }),
        el('th', { text: 'Grounded.' }), el('th', { text: 'Answer rel.' }))),
      tb));
    for (const q of qs) {
      tb.append(el('tr', null,
        el('td', { text: q.question }),
        el('td', { style: 'color:' + scoreColor(q.score), text: q.score != null ? Number(q.score).toFixed(3) : '–' }),
        el('td', { text: q.context != null ? Number(q.context).toFixed(3) : '–' }),
        el('td', { text: q.groundedness != null ? Number(q.groundedness).toFixed(3) : '–' }),
        el('td', { text: q.answer_relevance != null ? Number(q.answer_relevance).toFixed(3) : '–' })));
    }
    detailWrap.append(tw);
  }

  runBtn.onclick = async () => {
    runBtn.disabled = true;
    try {
      const r = await api('/eval/runs', { method: 'POST', json: { bundle_id: bundle.id } });
      toast('Eval run started.', 'success');
      detailWrap.innerHTML = '';
      refreshList();
      showRunDetail(r.run_id);
    } catch (e) {
      if (e.status === 422 && e.data && e.data.error === 'no_golden_set') {
        detailWrap.innerHTML = '';
        detailWrap.append(emptyState('eval', 'No golden set for this bundle',
          e.data.hint || 'Add a golden Q&A set to this bundle before running eval.'));
      } else {
        toast('Eval failed to start: ' + e.message, 'error');
      }
    }
    runBtn.disabled = false;
  };

  refreshList();
};

/* ============================== page: doctor ============================== */
ROUTES.doctor = function (view) {
  view.append(pageHead('Doctor', 'Environment and bundle health checks, straight from `okfsmith doctor`.'));
  const rerunBtn = el('button', { class: 'btn btn-primary', text: 'Re-run checks' });
  view.append(el('div', { class: 'row-between mb' }, el('div', { class: 'muted' }), rerunBtn));
  const wrap = el('div', { class: 'card' });
  view.append(wrap);

  async function load() {
    wrap.innerHTML = '';
    wrap.append(el('h3', { text: 'Health checks' }), skeletonBlock(4));
    let checks = [];
    try { checks = (await api('/doctor')).checks || []; }
    catch (e) { wrap.innerHTML = ''; wrap.append(el('h3', { text: 'Health checks' }), el('div', { class: 'muted', text: 'Doctor unavailable: ' + e.message })); return; }
    wrap.innerHTML = '';
    wrap.append(el('h3', { text: 'Health checks' }));
    const counts = { pass: 0, warn: 0, fail: 0 };
    for (const c of checks) { const s = String(c.status || '').toLowerCase(); if (counts[s] !== undefined) counts[s]++; }
    wrap.append(el('div', { class: 'mb', style: 'display:flex;gap:8px' },
      el('span', { class: 'pill pill-green', text: counts.pass + ' pass' }),
      el('span', { class: 'pill pill-amber', text: counts.warn + ' warn' }),
      el('span', { class: 'pill pill-red', text: counts.fail + ' fail' })));
    if (!checks.length) { wrap.append(el('div', { class: 'muted', text: 'No checks reported.' })); return; }
    for (const c of checks) {
      const st = String(c.status || '').toLowerCase();
      const pill = st === 'pass' ? el('span', { class: 'pill pill-green', text: 'pass' })
        : st === 'warn' ? el('span', { class: 'pill pill-amber', text: 'warn' })
        : st === 'fail' ? el('span', { class: 'pill pill-red', text: 'fail' })
        : el('span', { class: 'pill pill-muted', text: st || 'unknown' });
      wrap.append(el('div', { class: 'check-item' }, pill,
        el('div', { class: 'check-body' },
          el('div', { class: 'check-name', text: c.name }),
          el('div', { class: 'check-detail', text: c.detail || '' }))));
    }
  }
  rerunBtn.onclick = () => { toast('Re-running checks…'); load(); };
  load();
};

/* ============================== page: settings ============================== */
ROUTES.settings = function (view) {
  view.append(pageHead('Settings', 'Provider defaults and configuration. Secrets are write-only — the server never echoes them back.'));
  const wrap = el('div');
  view.append(wrap);
  wrap.append(skeletonBlock(6));

  (async () => {
    let data;
    try { data = await api('/settings'); }
    catch (e) { wrap.innerHTML = ''; wrap.append(el('div', { class: 'muted', text: 'Settings unavailable: ' + e.message })); return; }
    wrap.innerHTML = '';
    const providers = data.providers || [];
    const secretsSet = new Set(data.secrets_set || []);
    const config = data.config || {};

    // providers
    const provCard = el('div', { class: 'card mb' }, el('h3', { text: 'Providers' }));
    if (!providers.length) {
      provCard.append(el('div', { class: 'muted', text: 'No provider presets reported.' }));
    } else {
      const defSel = el('select', { class: 'select' });
      for (const p of providers) {
        defSel.append(el('option', { value: p.id, text: p.name + (p.description ? ' — ' + p.description : ''), selected: !!p.is_default }));
      }
      provCard.append(
        el('div', { class: 'form-field mb' }, el('label', { text: 'Default provider' }), defSel),
        el('div', { class: 'table-wrap' }));
      const tw = provCard.lastChild;
      const tb = el('tbody');
      tw.append(el('table', { class: 'data' },
        el('thead', null, el('tr', null, el('th', { text: 'Preset' }), el('th', { text: 'Description' }), el('th', { text: 'Default' }))),
        tb));
      for (const p of providers) {
        tb.append(el('tr', null,
          el('td', { class: 'mono', text: p.id }),
          el('td', { class: 'muted', text: p.description || '–' }),
          el('td', null, p.is_default ? el('span', { class: 'pill pill-accent', text: 'default' }) : el('span', { class: 'muted', text: '–' }))));
      }
      provCard._defSel = defSel;
    }
    wrap.append(provCard);

    // config (non-secret key/values as JSON)
    const cfgCard = el('div', { class: 'card mb' },
      el('h3', { text: 'Configuration' }),
      el('p', { class: 'muted small', text: 'Non-secret settings, edited as JSON. Invalid JSON will be rejected on save.' }));
    const cfgArea = el('textarea', { class: 'textarea', value: JSON.stringify(config, null, 2), style: 'min-height:180px' });
    cfgCard.append(cfgArea);
    wrap.append(cfgCard);

    // secrets (write-only)
    const secCard = el('div', { class: 'card mb' },
      el('h3', { text: 'Secrets' }),
      el('p', { class: 'muted small', text: 'Write-only. The server only reports whether a key is set — values are never shown.' }));
    const knownKeys = [...new Set([...secretsSet, 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'OPENROUTER_API_KEY'])];
    const secretInputs = {};
    for (const key of knownKeys) {
      const isSet = secretsSet.has(key);
      const inp = el('input', { class: 'input mono', type: 'password', placeholder: isSet ? '•••••••• (set — enter new value to replace)' : 'not set', autocomplete: 'new-password' });
      secretInputs[key] = inp;
      secCard.append(el('div', { class: 'secret-row' },
        el('span', { class: 'key', text: key }),
        isSet ? el('span', { class: 'pill pill-green', text: 'set' }) : el('span', { class: 'pill pill-muted', text: 'not set' }),
        inp));
    }
    wrap.append(secCard);

    const saveBtn = el('button', { class: 'btn btn-primary', text: 'Save settings' });
    wrap.append(saveBtn);
    saveBtn.onclick = async () => {
      let cfg;
      try { cfg = JSON.parse(cfgArea.value || '{}'); }
      catch (e) { toast('Config is not valid JSON: ' + e.message, 'error'); return; }
      const secrets = {};
      for (const [k, inp] of Object.entries(secretInputs)) {
        if (inp.value) secrets[k] = inp.value;
      }
      saveBtn.disabled = true;
      try {
        await api('/settings', { method: 'PUT', json: {
          config: cfg,
          default_provider: provCard._defSel ? provCard._defSel.value : null,
          secrets } });
        toast('Settings saved.', 'success');
        navigate();
      } catch (e) { toast('Save failed: ' + e.message, 'error'); }
      saveBtn.disabled = false;
    };
  })();
};
